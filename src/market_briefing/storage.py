from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
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
    ModuleCoverage,
    ModuleCoverageStatus,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunEvent,
    RunStatus,
    RunWarning,
    SourceType,
    can_transition_run,
)
from market_briefing.validation import validate_report_sections


class RunAlreadyExistsError(ValueError):
    pass


class InvalidRunTransitionError(ValueError):
    pass


class PublishedRecordExistsError(ValueError):
    pass


class AuditIntegrityError(RuntimeError):
    pass


class InvalidPublicationBundleError(ValueError):
    pass


class CandidateAlreadyExistsError(ValueError):
    pass


class CandidateAlreadyReviewedError(ValueError):
    pass


class InvalidCandidateReviewError(ValueError):
    pass


TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.FAILED,
}


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
    def __init__(
        self,
        database_path: Path,
        trusted_roots: tuple[Path, ...] | None = None,
    ):
        self.database_path = database_path
        self.trusted_roots = (
            tuple(Path(root).resolve() for root in trusted_roots) if trusted_roots else ()
        )

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
            legacy_snapshots = connection.execute(
                "select snapshot_id, raw_path from source_snapshots"
            ).fetchall()
            for snapshot in legacy_snapshots:
                raw_path = Path(snapshot["raw_path"])
                if not raw_path.is_file():
                    continue
                connection.execute(
                    "update source_snapshots set content_sha256 = ? where snapshot_id = ?",
                    (sha256(raw_path.read_bytes()).hexdigest(), snapshot["snapshot_id"]),
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
        report_columns = {
            row["name"] for row in connection.execute("pragma table_info(reports)").fetchall()
        }
        if "published_at" not in report_columns:
            connection.execute("alter table reports add column published_at text")
            connection.execute(
                """
                update reports
                set published_at = (
                    select runs.completed_at
                    from runs
                    where runs.run_id = reports.run_id
                      and runs.status in (?, ?)
                      and runs.completed_at is not null
                )
                where exists (
                    select 1
                    from runs
                    where runs.run_id = reports.run_id
                      and runs.status in (?, ?)
                      and runs.completed_at is not null
                )
                """,
                (
                    RunStatus.COMPLETED.value,
                    RunStatus.COMPLETED_WITH_WARNINGS.value,
                    RunStatus.COMPLETED.value,
                    RunStatus.COMPLETED_WITH_WARNINGS.value,
                ),
            )
        if "markdown_sha256" not in report_columns:
            connection.execute(
                "alter table reports add column markdown_sha256 text not null default ''"
            )
            self._backfill_report_artifact_hashes(connection, "markdown_sha256", "markdown_path")
        if "html_sha256" not in report_columns:
            connection.execute(
                "alter table reports add column html_sha256 text not null default ''"
            )
            self._backfill_report_artifact_hashes(connection, "html_sha256", "html_path")
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

    @staticmethod
    def _backfill_report_artifact_hashes(
        connection: sqlite3.Connection,
        hash_column: str,
        path_column: str,
    ) -> None:
        for row in connection.execute(
            f"select report_id, {path_column} from reports"
        ).fetchall():
            artifact_path = Path(row[path_column])
            if not artifact_path.is_file():
                continue
            connection.execute(
                f"update reports set {hash_column} = ? where report_id = ?",
                (sha256(artifact_path.read_bytes()).hexdigest(), row["report_id"]),
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
                self._assert_run_accepts_ledger_append(connection, snapshot.run_id)
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

    def rebase_snapshot_paths(
        self,
        run_id: str,
        paths_by_snapshot_id: dict[str, str],
    ) -> None:
        """暂存目录原子搬迁到 raw/ 后，重定位账本中的快照路径。

        仅允许在 run 尚未终态时调用，且不得改变内容哈希——路径变了，
        文件内容没变，这是同一份来源证据换了位置。
        """
        with self.connection() as connection:
            connection.execute("begin immediate")
            row = connection.execute(
                "select status from runs where run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if RunStatus(row["status"]) in TERMINAL_RUN_STATUSES:
                raise InvalidPublicationBundleError(
                    f"run {run_id} is terminal and cannot rebase snapshot paths"
                )
            for snapshot_id, raw_path in paths_by_snapshot_id.items():
                cursor = connection.execute(
                    "update source_snapshots set raw_path = ? where snapshot_id = ? and run_id = ?",
                    (raw_path, snapshot_id, run_id),
                )
                if cursor.rowcount != 1:
                    raise InvalidPublicationBundleError(
                        f"snapshot {snapshot_id} is not part of run {run_id}"
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
                self._assert_run_accepts_ledger_append(connection, candidate.run_id)
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
                for run_id in {fact.run_id for fact in facts}:
                    self._assert_run_accepts_ledger_append(connection, run_id)
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

    def save_run_warnings(self, warnings: list[RunWarning]) -> None:
        try:
            with self.connection() as connection:
                for run_id in {warning.run_id for warning in warnings}:
                    self._assert_run_accepts_ledger_append(connection, run_id)
                self._insert_run_warnings(connection, warnings)
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError("run warning") from exc

    @staticmethod
    def _insert_run_warnings(
        connection: sqlite3.Connection,
        warnings: list[RunWarning],
    ) -> None:
        records = [warning.to_record() for warning in warnings]
        connection.executemany(
            """
            insert into run_warnings (
                warning_id, run_id, source_name, module, message, detail, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record["warning_id"],
                    record["run_id"],
                    record["source_name"],
                    record["module"],
                    record["message"],
                    record["detail"],
                    record["created_at"],
                )
                for record in records
            ],
        )

    def list_run_warnings(self, run_id: str) -> list[RunWarning]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select * from run_warnings
                where run_id = ?
                order by created_at, warning_id
                """,
                (run_id,),
            ).fetchall()
        return [
            RunWarning(
                warning_id=row["warning_id"],
                run_id=row["run_id"],
                source_name=row["source_name"],
                module=row["module"],
                message=row["message"],
                detail=row["detail"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_module_coverage(self, coverage: list[ModuleCoverage]) -> None:
        try:
            with self.connection() as connection:
                for run_id in {item.run_id for item in coverage}:
                    self._assert_run_accepts_ledger_append(connection, run_id)
                self._insert_module_coverage(connection, coverage)
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError("module coverage") from exc

    @staticmethod
    def _insert_module_coverage(
        connection: sqlite3.Connection,
        coverage: list[ModuleCoverage],
    ) -> None:
        records = [item.to_record() for item in coverage]
        connection.executemany(
            """
            insert into module_coverage (
                coverage_id, run_id, module, status, source_name, message, recorded_at
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record["coverage_id"],
                    record["run_id"],
                    record["module"],
                    record["status"],
                    record["source_name"],
                    record["message"],
                    record["recorded_at"],
                )
                for record in records
            ],
        )

    def list_module_coverage_history(self, run_id: str) -> list[ModuleCoverage]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select * from module_coverage
                where run_id = ?
                order by recorded_at, coverage_id
                """,
                (run_id,),
            ).fetchall()
        return [self._module_coverage_from_row(row) for row in rows]

    def list_module_coverage(self, run_id: str) -> list[ModuleCoverage]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select coverage.*
                from module_coverage as coverage
                where coverage.run_id = ?
                  and coverage.rowid = (
                      select latest.rowid
                      from module_coverage as latest
                      where latest.run_id = coverage.run_id
                        and latest.module = coverage.module
                      order by latest.recorded_at desc, latest.rowid desc
                      limit 1
                  )
                order by coverage.module
                """,
                (run_id,),
            ).fetchall()
        return [self._module_coverage_from_row(row) for row in rows]

    @staticmethod
    def _module_coverage_from_row(row: sqlite3.Row) -> ModuleCoverage:
        return ModuleCoverage(
            coverage_id=row["coverage_id"],
            run_id=row["run_id"],
            module=row["module"],
            status=ModuleCoverageStatus(row["status"]),
            source_name=row["source_name"],
            message=row["message"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

    def save_report(self, report: Report) -> None:
        try:
            with self.connection() as connection:
                self._assert_run_accepts_ledger_append(connection, report.run_id)
                self._insert_report(connection, report)
        except sqlite3.IntegrityError as exc:
            raise PublishedRecordExistsError(report.report_id) from exc

    @staticmethod
    def _insert_report(
        connection: sqlite3.Connection,
        report: Report,
        *,
        published_at: datetime | None = None,
        markdown_sha256: str = "",
        html_sha256: str = "",
    ) -> None:
        connection.execute(
            """
            insert into reports (
                report_id, run_id, report_date, report_type, title,
                sections, markdown_path, html_path, fact_ledger_path, published_at,
                markdown_sha256, html_sha256
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                published_at.isoformat() if published_at else None,
                markdown_sha256,
                html_sha256,
            ),
        )

    def publish_run_bundle(
        self,
        *,
        snapshots: list[RawSnapshot],
        facts: list[AtomicFact],
        report: Report,
        target_status: RunStatus,
        warning_count: int | None = None,
        warnings: list[RunWarning] | None = None,
        module_coverage: list[ModuleCoverage] | None = None,
    ) -> Run:
        now = datetime.now(timezone.utc)
        run_warnings = warnings or []
        coverage_records = module_coverage or []
        next_warning_count = len(run_warnings) if warning_count is None else warning_count
        self._validate_publication_bundle(
            snapshots=snapshots,
            facts=facts,
            report=report,
            target_status=target_status,
            warning_count=next_warning_count,
            warnings=run_warnings,
            module_coverage=coverage_records,
        )
        markdown_sha256 = sha256(Path(report.markdown_path).read_bytes()).hexdigest()
        html_sha256 = sha256(Path(report.html_path).read_bytes()).hexdigest()
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
                self._assert_run_has_no_normal_ledger_records(connection, report.run_id)
                self._validate_candidate_audit_links(
                    connection,
                    facts=facts,
                    snapshots=snapshots,
                    run_id=report.run_id,
                )
                self._validate_candidate_review_resolution(
                    connection,
                    run_id=report.run_id,
                    facts=facts,
                )

                self._insert_snapshots(connection, snapshots)
                self._insert_facts(connection, facts)
                self._insert_report(
                    connection,
                    report,
                    published_at=now,
                    markdown_sha256=markdown_sha256,
                    html_sha256=html_sha256,
                )
                self._insert_run_warnings(connection, run_warnings)
                self._insert_module_coverage(connection, coverage_records)
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
                    (target_status.value, completed_at, next_warning_count, report.run_id),
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

    @staticmethod
    def _assert_run_accepts_ledger_append(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> None:
        row = connection.execute(
            "select status from runs where run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None and RunStatus(row["status"]) in TERMINAL_RUN_STATUSES:
            raise PublishedRecordExistsError(
                f"run {run_id} is terminal and cannot accept ledger records"
            )

    @staticmethod
    def _assert_run_has_no_normal_ledger_records(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> None:
        # 已进入人工审核阶段的 run 允许携带采集产物（ADR 0006 决策 2：采集与发布
        # 分两次写入同一 run）。但已发布事实与报告绝不可预置——那正是这条隔离
        # 要防的旁路。
        row = connection.execute(
            "select status from runs where run_id = ?",
            (run_id,),
        ).fetchone()
        collected_stage = row is not None and RunStatus(row["status"]) == RunStatus.AWAITING_REVIEW
        table_names = (
            ("reports", "facts")
            if collected_stage
            else ("source_snapshots", "facts", "reports", "run_warnings", "module_coverage")
        )
        occupied_tables = [
            table_name
            for table_name in table_names
            if connection.execute(
                f"select 1 from {table_name} where run_id = ? limit 1",
                (run_id,),
            ).fetchone()
            is not None
        ]
        if occupied_tables:
            raise InvalidPublicationBundleError(
                f"run {run_id} already has normal ledger records: "
                f"{', '.join(occupied_tables)}"
            )

    @staticmethod
    def _validate_candidate_audit_links(
        connection: sqlite3.Connection,
        *,
        facts: list[AtomicFact],
        snapshots: list[RawSnapshot],
        run_id: str,
    ) -> None:
        snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        # 采集与发布分两次写入同一 run 时，候选引用的快照可能已持久化在账本里。
        for persisted in _persisted_snapshots(connection, run_id):
            snapshot_by_id.setdefault(persisted.snapshot_id, persisted)
        for fact in facts:
            if not fact.source_candidate_id:
                continue
            candidate = connection.execute(
                "select * from evidence_candidates where candidate_id = ?",
                (fact.source_candidate_id,),
            ).fetchone()
            if candidate is None:
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} references missing candidate "
                    f"{fact.source_candidate_id}"
                )
            if candidate["run_id"] != run_id:
                raise InvalidPublicationBundleError(
                    f"candidate {fact.source_candidate_id} belongs to run "
                    f"{candidate['run_id']}"
                )
            if (
                candidate["module"] != fact.module
                or candidate["excerpt"] != fact.claim
                or candidate["suggested_classification"] != fact.classification.value
            ):
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} does not match candidate "
                    f"{fact.source_candidate_id}"
                )
            snapshot = snapshot_by_id.get(candidate["snapshot_id"])
            if snapshot is None or fact.source_snapshot_id != snapshot.snapshot_id:
                raise InvalidPublicationBundleError(
                    f"candidate {fact.source_candidate_id} does not match snapshot "
                    f"{fact.source_snapshot_id}"
                )
            review = connection.execute(
                """
                select to_status, approved_fact_id
                from candidate_review_events
                where candidate_id = ?
                order by event_id desc
                limit 1
                """,
                (fact.source_candidate_id,),
            ).fetchone()
            if review is None or review["to_status"] != CandidateReviewStatus.APPROVED.value:
                raise InvalidPublicationBundleError(
                    f"candidate {fact.source_candidate_id} is not approved"
                )
            if review["approved_fact_id"] != fact.fact_id:
                raise InvalidPublicationBundleError(
                    f"candidate {fact.source_candidate_id} does not approve fact "
                    f"{fact.fact_id}"
                )

    @staticmethod
    def _validate_candidate_review_resolution(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        facts: list[AtomicFact] | None = None,
    ) -> None:
        unresolved = connection.execute(
            """
            select candidates.candidate_id
            from evidence_candidates as candidates
            where candidates.run_id = ?
              and (
                select events.to_status
                from candidate_review_events as events
                where events.candidate_id = candidates.candidate_id
                order by events.event_id desc
                limit 1
              ) = ?
            order by candidates.candidate_id
            limit 1
            """,
            (run_id, CandidateReviewStatus.PENDING.value),
        ).fetchone()
        if unresolved is not None:
            raise InvalidPublicationBundleError(
                f"candidate {unresolved['candidate_id']} is not resolved"
            )
        if facts is None:
            return
        fact_candidate_by_id = {
            fact.fact_id: fact.source_candidate_id
            for fact in facts
        }
        approved_events = connection.execute(
            """
            select candidates.candidate_id, events.approved_fact_id
            from evidence_candidates as candidates
            join candidate_review_events as events
              on events.candidate_id = candidates.candidate_id
            where candidates.run_id = ?
              and events.event_id = (
                select latest.event_id
                from candidate_review_events as latest
                where latest.candidate_id = candidates.candidate_id
                order by latest.event_id desc
                limit 1
              )
              and events.to_status = ?
            order by candidates.candidate_id
            """,
            (run_id, CandidateReviewStatus.APPROVED.value),
        ).fetchall()
        for event in approved_events:
            if fact_candidate_by_id.get(event["approved_fact_id"]) != event["candidate_id"]:
                raise InvalidPublicationBundleError(
                    f"candidate {event['candidate_id']} approved fact "
                    f"{event['approved_fact_id']} is not in the publication bundle"
                )

    def _assert_path_within_trusted_roots(self, path: str) -> None:
        resolved = Path(path).resolve()
        if not any(resolved.is_relative_to(root) for root in self.trusted_roots):
            raise InvalidPublicationBundleError(f"path {path} is outside the trusted roots")

    def _validate_publication_bundle(
        self,
        *,
        snapshots: list[RawSnapshot],
        facts: list[AtomicFact],
        report: Report,
        target_status: RunStatus,
        warning_count: int,
        warnings: list[RunWarning],
        module_coverage: list[ModuleCoverage],
    ) -> None:
        if target_status not in {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_WARNINGS,
        }:
            raise InvalidPublicationBundleError(
                f"publication target must be a completed status: {target_status.value}"
            )
        if warning_count != len(warnings):
            raise InvalidPublicationBundleError(
                f"warning_count {warning_count} does not match {len(warnings)} warnings"
            )
        expected_status = (
            RunStatus.COMPLETED_WITH_WARNINGS if warnings else RunStatus.COMPLETED
        )
        if target_status != expected_status:
            raise InvalidPublicationBundleError(
                f"publication with {len(warnings)} warnings requires "
                f"{expected_status.value}"
            )
        run = self.get_run(report.run_id)
        if run is None:
            raise KeyError(report.run_id)
        if report.report_date != run.report_date or report.report_type != run.report_type:
            raise InvalidPublicationBundleError(
                f"report {report.report_id} does not match run {run.run_id}"
            )
        for label, path in (
            ("markdown", report.markdown_path),
            ("html", report.html_path),
            ("fact ledger", report.fact_ledger_path),
        ):
            if not Path(path).is_file():
                raise InvalidPublicationBundleError(
                    f"missing {label} file for {report.report_id}: {path}"
                )
        if self.trusted_roots:
            for path in (
                report.markdown_path,
                report.html_path,
                report.fact_ledger_path,
                *(snapshot.raw_path for snapshot in snapshots),
                *(fact.raw_snapshot_path for fact in facts),
            ):
                self._assert_path_within_trusted_roots(path)

        snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        if len(snapshot_by_id) != len(snapshots):
            raise InvalidPublicationBundleError("publication bundle contains duplicate snapshot IDs")
        # 采集与发布可以分两次写入同一 run：事实引用的快照可能已持久化在账本里。
        known_snapshots = {
            **{snapshot.snapshot_id: snapshot for snapshot in snapshots},
            **{
                snapshot.snapshot_id: snapshot
                for snapshot in self.list_snapshots(report.run_id)
                if snapshot.snapshot_id not in snapshot_by_id
            },
        }
        snapshot_by_path = {
            str(Path(snapshot.raw_path).resolve()): snapshot
            for snapshot in known_snapshots.values()
        }
        for snapshot in snapshots:
            if snapshot.run_id != report.run_id:
                raise InvalidPublicationBundleError(
                    f"snapshot {snapshot.snapshot_id} belongs to run {snapshot.run_id}"
                )
            if not verify_snapshot_hash(Path(snapshot.raw_path), snapshot.content_sha256):
                raise InvalidPublicationBundleError(
                    f"snapshot integrity check failed for {snapshot.snapshot_id}"
                )

        fact_ids = {fact.fact_id for fact in facts}
        if len(fact_ids) != len(facts):
            raise InvalidPublicationBundleError("publication bundle contains duplicate fact IDs")
        for fact in facts:
            if (
                fact.run_id != report.run_id
                or fact.report_date != report.report_date
                or fact.report_type != report.report_type
            ):
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} does not match report {report.report_id}"
                )
            snapshot = snapshot_by_path.get(str(Path(fact.raw_snapshot_path).resolve()))
            if snapshot is None:
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} references missing snapshot path "
                    f"{fact.raw_snapshot_path}"
                )
            if fact.source_snapshot_id and fact.source_snapshot_id != snapshot.snapshot_id:
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} source snapshot does not match its raw path"
                )
            missing_derived_fact_ids = set(fact.derived_from_fact_ids) - fact_ids
            if missing_derived_fact_ids:
                raise InvalidPublicationBundleError(
                    f"fact {fact.fact_id} derives from missing facts: "
                    f"{', '.join(sorted(missing_derived_fact_ids))}"
                )
        report_fact_ids = report.all_fact_ids() | {
            fact_line.fact_id
            for section in report.sections
            for fact_line in section.fact_lines
        }
        missing_report_fact_ids = report_fact_ids - fact_ids
        if missing_report_fact_ids:
            raise InvalidPublicationBundleError(
                f"report {report.report_id} cites missing facts: "
                f"{', '.join(sorted(missing_report_fact_ids))}"
            )
        report_validation = validate_report_sections(list(report.sections), facts)
        if not report_validation.ok:
            raise InvalidPublicationBundleError(
                "report validation failed: " + "; ".join(report_validation.errors)
            )
        for warning in warnings:
            if warning.run_id != report.run_id:
                raise InvalidPublicationBundleError(
                    f"warning {warning.warning_id} belongs to run {warning.run_id}"
                )
        for coverage in module_coverage:
            if coverage.run_id != report.run_id:
                raise InvalidPublicationBundleError(
                    f"coverage {coverage.coverage_id} belongs to run {coverage.run_id}"
                )

    def published_run_locations(self) -> set[tuple[str, str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select distinct reports.report_date, reports.report_type, reports.run_id
                from reports
                join runs on runs.run_id = reports.run_id
                where reports.published_at is not null
                  and runs.status in (?, ?)
                """,
                (RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value),
            ).fetchall()
        return {
            (row["report_date"], row["report_type"], row["run_id"])
            for row in rows
        }

    def assert_report_integrity(self, report_id: str) -> None:
        report = self.get_published_report(report_id)

        with self.connection() as connection:
            artifact_row = connection.execute(
                "select markdown_sha256, html_sha256 from reports where report_id = ?",
                (report.report_id,),
            ).fetchone()

        for label, path in (
            ("markdown", report.markdown_path),
            ("html", report.html_path),
            ("fact ledger", report.fact_ledger_path),
        ):
            if not Path(path).is_file():
                raise AuditIntegrityError(f"missing {label} file for {report.report_id}: {path}")
        for label, path, expected_sha256 in (
            ("markdown", report.markdown_path, artifact_row["markdown_sha256"]),
            ("html", report.html_path, artifact_row["html_sha256"]),
        ):
            if not expected_sha256:
                raise AuditIntegrityError(
                    f"missing {label} artifact hash for {report.report_id}"
                )
            if sha256(Path(path).read_bytes()).hexdigest() != expected_sha256:
                raise AuditIntegrityError(
                    f"{label} artifact integrity check failed for {report.report_id}: {path}"
                )
        snapshots = self.list_snapshots(report.run_id)
        facts = self.list_facts(report.run_id)
        snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
        snapshot_by_path = {str(Path(snapshot.raw_path).resolve()): snapshot for snapshot in snapshots}
        for snapshot in snapshots:
            if not verify_snapshot_hash(Path(snapshot.raw_path), snapshot.content_sha256):
                raise AuditIntegrityError(
                    f"snapshot integrity check failed for {snapshot.snapshot_id}"
                )
        for fact in facts:
            snapshot = snapshot_by_path.get(str(Path(fact.raw_snapshot_path).resolve()))
            if snapshot is None:
                raise AuditIntegrityError(
                    f"fact {fact.fact_id} references missing snapshot path "
                    f"{fact.raw_snapshot_path}"
                )
            if fact.source_snapshot_id:
                linked_snapshot = snapshot_by_id.get(fact.source_snapshot_id)
                if linked_snapshot is None or linked_snapshot.snapshot_id != snapshot.snapshot_id:
                    raise AuditIntegrityError(
                        f"fact {fact.fact_id} source snapshot does not match its raw path"
                    )
        try:
            with self.connection() as connection:
                self._validate_candidate_audit_links(
                    connection,
                    facts=facts,
                    snapshots=snapshots,
                    run_id=report.run_id,
                )
                self._validate_candidate_review_resolution(
                    connection,
                    run_id=report.run_id,
                )
        except InvalidPublicationBundleError as exc:
            raise AuditIntegrityError(str(exc)) from exc

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

    def get_published_report(self, report_id: str) -> Report:
        with self.connection() as connection:
            row = connection.execute(
                """
                select reports.report_id
                from reports
                join runs on runs.run_id = reports.run_id
                where reports.report_id = ?
                  and reports.published_at is not null
                  and runs.status in (?, ?)
                """,
                (
                    report_id,
                    RunStatus.COMPLETED.value,
                    RunStatus.COMPLETED_WITH_WARNINGS.value,
                ),
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        return self.get_report(row["report_id"])

    def list_reports(self) -> list[Report]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                select reports.report_id
                from reports
                join runs on runs.run_id = reports.run_id
                where reports.published_at is not null
                  and runs.status in (?, ?)
                order by
                    reports.report_date desc,
                    coalesce(
                        runs.completed_at,
                        runs.created_at,
                        reports.report_date || 'T00:00:00'
                    ) desc,
                    reports.report_id desc
                """,
                (RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_WARNINGS.value),
            ).fetchall()
        return [self.get_published_report(row["report_id"]) for row in rows]

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


def _persisted_snapshots(
    connection: sqlite3.Connection,
    run_id: str,
) -> list[RawSnapshot]:
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

create table if not exists run_warnings (
    warning_id text primary key,
    run_id text not null,
    source_name text not null,
    module text not null,
    message text not null,
    detail text,
    created_at text not null
);

create index if not exists idx_run_warnings_run_id
on run_warnings (run_id, created_at, warning_id);

create table if not exists module_coverage (
    coverage_id text primary key,
    run_id text not null,
    module text not null,
    status text not null,
    source_name text,
    message text not null,
    recorded_at text not null
);

create index if not exists idx_module_coverage_run_id
on module_coverage (run_id, module, recorded_at, coverage_id);

create table if not exists reports (
    report_id text primary key,
    run_id text not null,
    report_date text not null,
    report_type text not null,
    title text not null,
    sections text not null,
    markdown_path text not null,
    html_path text not null,
    fact_ledger_path text not null,
    published_at text,
    markdown_sha256 text not null default '',
    html_sha256 text not null default ''
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
