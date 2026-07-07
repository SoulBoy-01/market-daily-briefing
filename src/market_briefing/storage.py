from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FactLine,
    FeedbackEntry,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    SourceType,
)


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

    def save_run(self, run: Run) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                insert into runs (
                    run_id, report_date, report_type, enabled_modules, status,
                    created_at, started_at, completed_at, warning_count, error_message
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    report_date=excluded.report_date,
                    report_type=excluded.report_type,
                    enabled_modules=excluded.enabled_modules,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    warning_count=excluded.warning_count,
                    error_message=excluded.error_message
                """,
                (
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
                ),
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
        )

    def save_snapshot(self, snapshot: RawSnapshot) -> None:
        record = snapshot.to_record()
        with self.connection() as connection:
            connection.execute(
                """
                insert into source_snapshots (
                    snapshot_id, run_id, module, source_name, source_url, source_type,
                    fetched_at, content_type, raw_path, metadata
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(snapshot_id) do update set
                    run_id=excluded.run_id,
                    module=excluded.module,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    source_type=excluded.source_type,
                    fetched_at=excluded.fetched_at,
                    content_type=excluded.content_type,
                    raw_path=excluded.raw_path,
                    metadata=excluded.metadata
                """,
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
                    _to_json(record["metadata"]),
                ),
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
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def save_facts(self, facts: list[AtomicFact]) -> None:
        records = [fact.to_record() for fact in facts]
        with self.connection() as connection:
            connection.executemany(
                """
                insert into facts (
                    fact_id, run_id, report_date, report_type, module, claim, classification,
                    source_name, source_url, source_type, published_at, fetched_at, confidence,
                    raw_snapshot_path, derived_from_fact_ids, used_in_sections
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(fact_id) do update set
                    run_id=excluded.run_id,
                    report_date=excluded.report_date,
                    report_type=excluded.report_type,
                    module=excluded.module,
                    claim=excluded.claim,
                    classification=excluded.classification,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    source_type=excluded.source_type,
                    published_at=excluded.published_at,
                    fetched_at=excluded.fetched_at,
                    confidence=excluded.confidence,
                    raw_snapshot_path=excluded.raw_snapshot_path,
                    derived_from_fact_ids=excluded.derived_from_fact_ids,
                    used_in_sections=excluded.used_in_sections
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
            )
            for row in rows
        ]

    def save_report(self, report: Report) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                insert into reports (
                    report_id, run_id, report_date, report_type, title,
                    sections, markdown_path, html_path, fact_ledger_path
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(report_id) do update set
                    run_id=excluded.run_id,
                    report_date=excluded.report_date,
                    report_type=excluded.report_type,
                    title=excluded.title,
                    sections=excluded.sections,
                    markdown_path=excluded.markdown_path,
                    html_path=excluded.html_path,
                    fact_ledger_path=excluded.fact_ledger_path
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
    error_message text
);

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
    metadata text not null
);

create index if not exists idx_source_snapshots_run_id
on source_snapshots (run_id);

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
    used_in_sections text not null
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
