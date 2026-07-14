from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_briefing.audit import verify_snapshot_hash
from market_briefing.domain import (
    AtomicFact,
    CandidateReviewEvent,
    CandidateReviewStatus,
    EvidenceCandidate,
    FactClassification,
    FactLine,
    FeedbackEntry,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunEvent,
    RunStatus,
    SourceType,
    can_transition_run,
)


class RunAlreadyExistsError(ValueError):
    pass


class InvalidRunTransitionError(ValueError):
    pass


class PublishedRecordExistsError(ValueError):
    pass


class AuditIntegrityError(RuntimeError):
    pass


class CandidateAlreadyExistsError(ValueError):
    pass


class CandidateAlreadyReviewedError(ValueError):
    pass


class InvalidCandidateReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ReportPaths:
    report_dir: Path
    markdown_path: Path
    html_path: Path
    fact_ledger_path: Path


def build_report_paths(
    reports_dir: Path,
    report_date: str,
    report_type: ReportType,
    run_id: str,
) -> ReportPaths:
    report_dir = reports_dir / report_date / report_type.value / run_id
    return ReportPaths(
        report_dir=report_dir,
        markdown_path=report_dir / "briefing.md",
        html_path=report_dir / "briefing.html",
        fact_ledger_path=report_dir / "fact_ledger.json",
    )


class BriefingStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            self._migrate_schema(connection)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        run_columns = {
            row["name"] for row in connection.execute("pragma table_info(runs)").fetchall()
        }
        if "supersedes_run_id" not in run_columns:
            connection.execute("alter table runs add column supersedes_run_id text")
        snapshot_columns = {
            row["name"]
            for row in connection.execute("pragma table_info(source_snapshots)").fetchall()
        }
        if "content_sha256" not in snapshot_columns:
            connection.execute(
                "alter table source_snapshots add column content_sha256 text not null default ''"
            )
        if "provider_name" not in snapshot_columns:
            connection.execute(
                "alter table source_snapshots add column provider_name text not null default ''"
            )
            connection.execute(
                "update source_snapshots set provider_name = source_name where provider_name = ''"
            )
        if "license_ref" not in snapshot_columns:
            connection.execute("alter table source_snapshots add column license_ref text")
        fact_columns = {
            row["name"] for row in connection.execute("pragma table_info(facts)").fetchall()
        }
        if "source_candidate_id" not in fact_columns:
            connection.execute("alter table facts add column source_candidate_id text")
        if "source_snapshot_id" not in fact_columns:
            connection.execute("alter table facts add column source_snapshot_id text")
        connection.execute(
            """
            insert into run_events (run_id, from_status, to_status, created_at)
            select runs.run_id, null, runs.status, coalesce(runs.completed_at, runs.created_at)
            from runs
            where not exists (
                select 1 from run_events where run_events.run_id = runs.run_id
            )
            """
        )

    def create_run(self, run: Run) -> None:
        try:
            with self.connection() as connection:
                connection.execute(
                    """
                    insert into runs (
                        run_id, report_date, report_type, enabled_modules, status,
                        created_at, started_at, completed_at, warning_count, error_message,
                        supersedes_run_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._run_values(run),
                )
                connection.execute(
                    """
                    insert into run_events (run_id, from_status, to_status, created_at)
                    values (?, ?, ?, ?)
                    """,
                    (run.run_id, None, run.status.value, run.created_at.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            if "runs.run_id" in str(exc):
                raise RunAlreadyExistsError(run.run_id) from exc
            raise

    def transition_run(
        self,
        run_id: str,
        target_status: RunStatus,
        *,
        warning_count: int | None = None,
        error_message: str | None = None,
    ) -> Run:
        now = datetime.now(timezone.utc)
        with self.connection() as connection:
            connection.execute("begin immediate")
            row = connection.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            current_status = RunStatus(row["status"])
            if not can_transition_run(current_status, target_status):
                raise InvalidRunTransitionError(
                    f"cannot transition run {run_id} from {current_status.value} "
                    f"to {target_status.value}"
                )
            started_at = row["started_at"]
            completed_at = row["completed_at"]
            if target_status == RunStatus.RUNNING and started_at is None:
                started_at = now.isoformat()
            if target_status in {
                RunStatus.COMPLETED,
                RunStatus.COMPLETED_WITH_WARNINGS,
                RunStatus.FAILED,
            }:
                completed_at = now.isoformat()
            next_warning_count = (
                row["warning_count"] if warning_count is None else warning_count
            )
            next_error_message = row["error_message"] if error_message is None else error_message
            connection.execute(
                """
                update runs
                set status = ?, started_at = ?, completed_at = ?,
                    warning_count = ?, error_message = ?
                where run_id = ?
                """,
                (
                    target_status.value,
                    started_at,
                    completed_at,
                    next_warning_count,
                    next_error_message,
                    run_id,
                ),
            )
            connection.execute(
                """
                insert into run_events (run_id, from_status, to_status, created_at)
                values (?, ?, ?, ?)
                """,
                (run_id, current_status.value, target_status.value, now.isoformat()),
            )
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def list_run_events(self, run_id: str) -> list[RunEvent]:
        with self.connection() as connection:
            rows = connection.execute(
                "select * from run_events where run_id = ? order by event_id",
                (run_id,),
            ).fetchall()
        return [
            RunEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                from_status=(RunStatus(row["from_status"]) if row["from_status"] else None),
                to_status=RunStatus(row["to_status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_run(self, run: Run) -> None:
        self.create_run(run)

    @staticmethod
    def _run_values(run: Run) -> tuple[Any, ...]:
        return (
            run.run_id,
            run.report_date,
            run.report_type.value,
            _to_json(list(run.enabled_modules)),
            run.status.value,
            run.created_at.isoformat(),
            run.started_at.isoformat() if run.started_at else None,
            run.completed_at.isoformat() if run.completed_at else None,
            run.warning_count,
            run.error_message,
            run.supersedes_run_id,
        )

    def get_run(self, run_id: str) -> Run | None:
        with self.connection() as connection:
            row = connection.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            run_id=row["run_id"],
            report_date=row["report_date"],
            report_type=ReportType(row["report_type"]),
            enabled_modules=json.loads(row["enabled_modules"]),
            status=RunStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            warning_count=row["warning_count"],
            error_message=row["error_message"],
            supersedes_run_id=row["supersedes_run_id"],
        )

    def save_snapshot(self, snapshot: RawSnapshot) -> None:
        try:
            with self.connection() as connection:
                self._insert_snapshots(connection, [snapshot])
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError(snapshot.snapshot_id) from exc

    @staticmethod
    def _insert_snapshots(
        connection: sqlite3.Connection,
        snapshots: list[RawSnapshot],
    ) -> None:
        records = [snapshot.to_record() for snapshot in snapshots]
        connection.executemany(
            """
            insert into source_snapshots (
                snapshot_id, run_id, module, source_name, source_url, source_type,
                fetched_at, content_type, raw_path, content_sha256, provider_name,
                license_ref, metadata
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record["snapshot_id"],
                    record["run_id"],
                    record["module"],
                    record["source_name"],
                    record["source_url"],
                    record["source_type"],
                    record["fetched_at"],
                    record["content_type"],
                    record["raw_path"],
                    record["content_sha256"],
                    record["provider_name"],
                    record["license_ref"],
                    _to_json(record["metadata"]),
                )
                for record in records
            ],
        )

    def list_snapshots(self, run_id: str) -> list[RawSnapshot]:
        with self.connection() as connection:
            rows = connection.execute(
                "select * from source_snapshots where run_id = ? order by snapshot_id",
                (run_id,),
            ).fetchall()
        return [
            RawSnapshot(
                snapshot_id=row["snapshot_id"],
                run_id=row["run_id"],
                module=row["module"],
                source_name=row["source_name"],
                source_url=row["source_url"],
                source_type=SourceType(row["source_type"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                content_type=row["content_type"],
                raw_path=row["raw_path"],
                content_sha256=row["content_sha256"],
                provider_name=row["provider_name"],
                license_ref=row["license_ref"],
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def save_candidate(self, candidate: EvidenceCandidate) -> None:
        record = candidate.to_record()
        try:
            with self.connection() as connection:
                connection.execute(
                    """
                    insert into evidence_candidates (
                        candidate_id, run_id, snapshot_id, module, title, detail_url,
                        published_at, excerpt, suggested_classification, created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["candidate_id"],
                        record["run_id"],
                        record["snapshot_id"],
                        record["module"],
                        record["title"],
                        record["detail_url"],
                        record["published_at"],
                        record["excerpt"],
                        record["suggested_classification"],
                        record["created_at"],
                    ),
                )
                connection.execute(
                    """
                    insert into candidate_review_events (
                        candidate_id, from_status, to_status, reviewed_at,
                        reviewer_id, note, approved_fact_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.candidate_id,
                        None,
                        CandidateReviewStatus.PENDING.value,
                        candidate.created_at.isoformat(),
                        None,
                        "",
                        None,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise CandidateAlreadyExistsError(candidate.candidate_id) from exc

    def get_candidate(self, candidate_id: str) -> EvidenceCandidate:
        with self.connection() as connection:
            row = connection.execute(
                "select * from evidence_candidates where candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return EvidenceCandidate(
            candidate_id=row["candidate_id"],
            run_id=row["run_id"],
            snapshot_id=row["snapshot_id"],
            module=row["module"],
            title=row["title"],
            detail_url=row["detail_url"],
            published_at=(
                datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
            ),
            excerpt=row["excerpt"],
            suggested_classification=FactClassification(row["suggested_classification"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_candidate_review_events(self, candidate_id: str) -> list[CandidateReviewEvent]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select * from candidate_review_events
                where candidate_id = ?
                order by event_id
                """,
                (candidate_id,),
            ).fetchall()
        return [self._candidate_review_event_from_row(row) for row in rows]

    def candidate_review_status(self, candidate_id: str) -> CandidateReviewStatus:
        with self.connection() as connection:
            candidate = connection.execute(
                "select 1 from evidence_candidates where candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            row = connection.execute(
                """
                select to_status from candidate_review_events
                where candidate_id = ?
                order by event_id desc
                limit 1
                """,
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"candidate {candidate_id} has no review event")
        return CandidateReviewStatus(row["to_status"])

    def review_candidate(
        self,
        candidate_id: str,
        target_status: CandidateReviewStatus,
        *,
        reviewer_id: str,
        note: str,
        approved_fact_id: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> CandidateReviewEvent:
        if target_status not in {
            CandidateReviewStatus.APPROVED,
            CandidateReviewStatus.REJECTED,
        }:
            raise InvalidCandidateReviewError(target_status.value)
        if target_status == CandidateReviewStatus.APPROVED and not approved_fact_id:
            raise InvalidCandidateReviewError("approved review requires approved_fact_id")
        if target_status == CandidateReviewStatus.REJECTED and approved_fact_id is not None:
            raise InvalidCandidateReviewError("rejected review cannot reference a fact")

        event_time = reviewed_at or datetime.now(timezone.utc)
        with self.connection() as connection:
            connection.execute("begin immediate")
            candidate = connection.execute(
                "select 1 from evidence_candidates where candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(candidate_id)
            current = connection.execute(
                """
                select to_status from candidate_review_events
                where candidate_id = ?
                order by event_id desc
                limit 1
                """,
                (candidate_id,),
            ).fetchone()
            if current is None:
                raise RuntimeError(f"candidate {candidate_id} has no review event")
            current_status = CandidateReviewStatus(current["to_status"])
            if current_status != CandidateReviewStatus.PENDING:
                raise CandidateAlreadyReviewedError(candidate_id)
            cursor = connection.execute(
                """
                insert into candidate_review_events (
                    candidate_id, from_status, to_status, reviewed_at,
                    reviewer_id, note, approved_fact_id
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    current_status.value,
                    target_status.value,
                    event_time.isoformat(),
                    reviewer_id,
                    note,
                    approved_fact_id,
                ),
            )
            event_id = cursor.lastrowid
        if event_id is None:
            raise RuntimeError("candidate review event did not receive an ID")
        return CandidateReviewEvent(
            event_id=event_id,
            candidate_id=candidate_id,
            from_status=current_status,
            to_status=target_status,
            reviewed_at=event_time,
            reviewer_id=reviewer_id,
            note=note,
            approved_fact_id=approved_fact_id,
        )

    @staticmethod
    def _candidate_review_event_from_row(row: sqlite3.Row) -> CandidateReviewEvent:
        return CandidateReviewEvent(
            event_id=row["event_id"],
            candidate_id=row["candidate_id"],
            from_status=(
                CandidateReviewStatus(row["from_status"]) if row["from_status"] else None
            ),
            to_status=CandidateReviewStatus(row["to_status"]),
            reviewed_at=datetime.fromisoformat(row["reviewed_at"]),
            reviewer_id=row["reviewer_id"],
            note=row["note"],
            approved_fact_id=row["approved_fact_id"],
        )

    def save_facts(self, facts: list[AtomicFact]) -> None:
        try:
            with self.connection() as connection:
                self._insert_facts(connection, facts)
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError("fact") from exc

    @staticmethod
    def _insert_facts(
        connection: sqlite3.Connection,
        facts: list[AtomicFact],
    ) -> None:
        records = [fact.to_record() for fact in facts]
        connection.executemany(
            """
            insert into facts (
                fact_id, run_id, report_date, report_type, module, claim, classification,
                source_name, source_url, source_type, published_at, fetched_at, confidence,
                raw_snapshot_path, derived_from_fact_ids, used_in_sections,
                source_candidate_id, source_snapshot_id
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record["fact_id"],
                    record["run_id"],
                    record["report_date"],
                    record["report_type"],
                    record["module"],
                    record["claim"],
                    record["classification"],
                    record["source_name"],
                    record["source_url"],
                    record["source_type"],
                    record["published_at"],
                    record["fetched_at"],
                    record["confidence"],
                    record["raw_snapshot_path"],
                    _to_json(record["derived_from_fact_ids"]),
                    _to_json(record["used_in_sections"]),
                    record["source_candidate_id"],
                    record["source_snapshot_id"],
                )
                for record in records
            ],
        )

    def list_facts(self, run_id: str) -> list[AtomicFact]:
        with self.connection() as connection:
            rows = connection.execute(
                "select * from facts where run_id = ? order by fact_id",
                (run_id,),
            ).fetchall()
        return [
            AtomicFact(
                fact_id=row["fact_id"],
                run_id=row["run_id"],
                report_date=row["report_date"],
                report_type=ReportType(row["report_type"]),
                module=row["module"],
                claim=row["claim"],
                classification=FactClassification(row["classification"]),
                source_name=row["source_name"],
                source_url=row["source_url"],
                source_type=SourceType(row["source_type"]),
                published_at=(
                    datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
                ),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                confidence=row["confidence"],
                raw_snapshot_path=row["raw_snapshot_path"],
                derived_from_fact_ids=json.loads(row["derived_from_fact_ids"]),
                used_in_sections=json.loads(row["used_in_sections"]),
                source_candidate_id=row["source_candidate_id"],
                source_snapshot_id=row["source_snapshot_id"],
            )
            for row in rows
        ]

    def save_report(self, report: Report) -> None:
        try:
            with self.connection() as connection:
                self._insert_report(connection, report)
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError(report.report_id) from exc

    @staticmethod
    def _insert_report(connection: sqlite3.Connection, report: Report) -> None:
        connection.execute(
            """
            insert into reports (
                report_id, run_id, report_date, report_type, title,
                sections, markdown_path, html_path, fact_ledger_path
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.run_id,
                report.report_date,
                report.report_type.value,
                report.title,
                _to_json([_section_to_record(section) for section in report.sections]),
                report.markdown_path,
                report.html_path,
                report.fact_ledger_path,
            ),
        )

    def publish_run_bundle(
        self,
        *,
        snapshots: list[RawSnapshot],
        facts: list[AtomicFact],
        report: Report,
        target_status: RunStatus,
        warning_count: int = 0,
    ) -> Run:
        now = datetime.now(timezone.utc)
        try:
            with self.connection() as connection:
                connection.execute("begin immediate")
                row = connection.execute(
                    "select * from runs where run_id = ?",
                    (report.run_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(report.run_id)
                current_status = RunStatus(row["status"])
                if not can_transition_run(current_status, target_status):
                    raise InvalidRunTransitionError(
                        f"cannot transition run {report.run_id} from {current_status.value} "
                        f"to {target_status.value}"
                    )

                self._insert_snapshots(connection, snapshots)
                self._insert_facts(connection, facts)
                self._insert_report(connection, report)
                completed_at = (
                    now.isoformat()
                    if target_status
                    in {
                        RunStatus.COMPLETED,
                        RunStatus.COMPLETED_WITH_WARNINGS,
                        RunStatus.FAILED,
                    }
                    else row["completed_at"]
                )
                connection.execute(
                    """
                    update runs
                    set status = ?, completed_at = ?, warning_count = ?
                    where run_id = ?
                    """,
                    (target_status.value, completed_at, warning_count, report.run_id),
                )
                connection.execute(
                    """
                    insert into run_events (run_id, from_status, to_status, created_at)
                    values (?, ?, ?, ?)
                    """,
                    (
                        report.run_id,
                        current_status.value,
                        target_status.value,
                        now.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError(report.run_id) from exc

        run = self.get_run(report.run_id)
        if run is None:
            raise KeyError(report.run_id)
        return run

    def published_run_ids(self) -> set[str]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select distinct reports.run_id
                from reports
                join runs on runs.run_id = reports.run_id
                where runs.status in (?, ?)
                """,
                (RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value),
            ).fetchall()
        return {row["run_id"] for row in rows}

    def assert_report_integrity(self, report_id: str) -> None:
        report = self.get_report(report_id)
        run = self.get_run(report.run_id)
        if run is None or run.status not in {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
        }:
            return

        for label, path in (
            ("markdown", report.markdown_path),
            ("html", report.html_path),
            ("fact ledger", report.fact_ledger_path),
        ):
            if not Path(path).is_file():
                raise AuditIntegrityError(f"missing {label} file for {report.report_id}: {path}")
        for snapshot in self.list_snapshots(report.run_id):
            if not verify_snapshot_hash(Path(snapshot.raw_path), snapshot.content_sha256):
                raise AuditIntegrityError(
                    f"snapshot integrity check failed for {snapshot.snapshot_id}"
                )

    def get_report(self, report_id: str) -> Report:
        with self.connection() as connection:
            row = connection.execute(
                "select * from reports where report_id = ?",
                (report_id,),
            ).fetchone()
        if row is None:
            raise KeyError(report_id)

        sections_payload: list[dict[str, Any]] = json.loads(row["sections"])
        return Report(
            report_id=row["report_id"],
            run_id=row["run_id"],
            report_date=row["report_date"],
            report_type=ReportType(row["report_type"]),
            title=row["title"],
            sections=[_section_from_record(section) for section in sections_payload],
            markdown_path=row["markdown_path"],
            html_path=row["html_path"],
            fact_ledger_path=row["fact_ledger_path"],
        )

    def list_reports(self) -> list[Report]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select reports.report_id
                from reports
                left join runs on runs.run_id = reports.run_id
                order by
                    reports.report_date desc,
                    coalesce(
                        runs.completed_at,
                        runs.created_at,
                        reports.report_date || 'T00:00:00'
                    ) desc,
                    reports.report_id desc
                """
            ).fetchall()
        return [self.get_report(row["report_id"]) for row in rows]

    def latest_report(self) -> Report | None:
        reports = self.list_reports()
        if not reports:
            return None
        return reports[0]

    def save_feedback(self, entry: FeedbackEntry) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                insert into feedback (
                    feedback_id, report_id, section_id, score, tags, note, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.feedback_id,
                    entry.report_id,
                    entry.section_id,
                    entry.score,
                    _to_json(list(entry.tags)),
                    entry.note,
                    entry.created_at.isoformat(),
                ),
            )

    def list_feedback(self, report_id: str) -> list[FeedbackEntry]:
        with self.connection() as connection:
            rows = connection.execute(
                "select * from feedback where report_id = ? order by created_at, feedback_id",
                (report_id,),
            ).fetchall()
        return [
            FeedbackEntry(
                feedback_id=row["feedback_id"],
                report_id=row["report_id"],
                section_id=row["section_id"],
                score=row["score"],
                tags=json.loads(row["tags"]),
                note=row["note"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _section_to_record(section: ReportSection) -> dict[str, Any]:
    return {
        "section_id": section.section_id,
        "title": section.title,
        "body": section.body,
        "fact_ids": list(section.fact_ids),
        "status": section.status,
        "fact_lines": [
            {
                "fact_id": fact_line.fact_id,
                "classification": fact_line.classification.value,
                "claim": fact_line.claim,
                "derived_from_fact_ids": list(fact_line.derived_from_fact_ids),
            }
            for fact_line in section.fact_lines
        ],
    }


def _section_from_record(payload: dict[str, Any]) -> ReportSection:
    return ReportSection(
        section_id=payload["section_id"],
        title=payload["title"],
        body=payload["body"],
        fact_ids=payload["fact_ids"],
        status=payload["status"],
        fact_lines=[
            FactLine(
                fact_id=fact_line["fact_id"],
                classification=FactClassification(fact_line["classification"]),
                claim=fact_line["claim"],
                derived_from_fact_ids=fact_line.get("derived_from_fact_ids", []),
            )
            for fact_line in payload.get("fact_lines", [])
        ],
    )


SCHEMA = """
create table if not exists runs (
    run_id text primary key,
    report_date text not null,
    report_type text not null,
    enabled_modules text not null,
    status text not null,
    created_at text not null,
    started_at text,
    completed_at text,
    warning_count integer not null default 0,
    error_message text,
    supersedes_run_id text
);

create table if not exists run_events (
    event_id integer primary key autoincrement,
    run_id text not null,
    from_status text,
    to_status text not null,
    created_at text not null
);

create index if not exists idx_run_events_run_id
on run_events (run_id, event_id);

create table if not exists source_snapshots (
    snapshot_id text primary key,
    run_id text not null,
    module text not null,
    source_name text not null,
    source_url text not null,
    source_type text not null,
    fetched_at text not null,
    content_type text not null,
    raw_path text not null,
    content_sha256 text not null default '',
    provider_name text not null default '',
    license_ref text,
    metadata text not null
);

create index if not exists idx_source_snapshots_run_id
on source_snapshots (run_id);

create table if not exists evidence_candidates (
    candidate_id text primary key,
    run_id text not null,
    snapshot_id text not null,
    module text not null,
    title text not null,
    detail_url text not null,
    published_at text,
    excerpt text not null,
    suggested_classification text not null,
    created_at text not null
);

create index if not exists idx_evidence_candidates_run_id
on evidence_candidates (run_id, candidate_id);

create table if not exists candidate_review_events (
    event_id integer primary key autoincrement,
    candidate_id text not null,
    from_status text,
    to_status text not null,
    reviewed_at text not null,
    reviewer_id text,
    note text not null,
    approved_fact_id text
);

create index if not exists idx_candidate_review_events_candidate_id
on candidate_review_events (candidate_id, event_id);

create table if not exists facts (
    fact_id text primary key,
    run_id text not null,
    report_date text not null,
    report_type text not null,
    module text not null,
    claim text not null,
    classification text not null,
    source_name text not null,
    source_url text not null,
    source_type text not null,
    published_at text,
    fetched_at text not null,
    confidence text not null,
    raw_snapshot_path text not null,
    derived_from_fact_ids text not null,
    used_in_sections text not null,
    source_candidate_id text,
    source_snapshot_id text
);

create index if not exists idx_facts_run_id
on facts (run_id);

create table if not exists reports (
    report_id text primary key,
    run_id text not null,
    report_date text not null,
    report_type text not null,
    title text not null,
    sections text not null,
    markdown_path text not null,
    html_path text not null,
    fact_ledger_path text not null
);

create table if not exists feedback (
    feedback_id text primary key,
    report_id text not null,
    section_id text not null,
    score integer not null,
    tags text not null,
    note text not null,
    created_at text not null
);
"""
