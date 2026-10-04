from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

import pytest

from market_briefing.audit import write_snapshot_text
from market_briefing.domain import (
    AtomicFact,
    CandidateReviewStatus,
    EvidenceCandidate,
    FactClassification,
    FactLine,
    ModuleCoverage,
    ModuleCoverageStatus,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    RunWarning,
    SourceType,
)
from market_briefing.storage import (
    AuditIntegrityError,
    BriefingStore,
    CandidateAlreadyExistsError,
    CandidateAlreadyReviewedError,
    InvalidPublicationBundleError,
    InvalidRunTransitionError,
    RunAlreadyExistsError,
    PublishedRecordExistsError,
    SCHEMA,
    build_report_paths,
)


class TrackingConnection(sqlite3.Connection):
    close_count = 0

    def close(self) -> None:
        type(self).close_count += 1
        super().close()


class TrackingStore(BriefingStore):
    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, factory=TrackingConnection)
        connection.row_factory = sqlite3.Row
        return connection


def _candidate(candidate_id: str = "candidate-001") -> EvidenceCandidate:
    return EvidenceCandidate(
        candidate_id=candidate_id,
        run_id="run-candidates",
        snapshot_id="snapshot-candidates",
        module="policy_regulation",
        title="交易所发布一项规则说明",
        detail_url="https://example.test/rule-001",
        published_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
        excerpt="规则说明自发布之日起施行。",
        suggested_classification=FactClassification.FACT,
        created_at=datetime(2026, 7, 2, 8, 5, tzinfo=timezone.utc),
    )


def _publication_material(tmp_path, run: Run, suffix: str = ""):
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    snapshot_file = write_snapshot_text(tmp_path / f"snapshot{suffix}.json", "{}")
    snapshot = RawSnapshot(
        snapshot_id=f"snapshot{suffix}",
        run_id=run.run_id,
        module="market_indices",
        source_name="Fixture",
        source_url=f"fixture://snapshot{suffix}",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    fact = AtomicFact(
        fact_id=f"fact{suffix}",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        module="market_indices",
        claim="Publication material fact.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url=f"fixture://snapshot{suffix}",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=str(snapshot_file.path),
        source_snapshot_id=snapshot.snapshot_id,
    )
    report_files = [
        tmp_path / f"report{suffix}.md",
        tmp_path / f"report{suffix}.html",
        tmp_path / f"report{suffix}.json",
    ]
    for report_file in report_files:
        report_file.write_text("report artifact", encoding="utf-8")
    report = Report(
        report_id=f"report{suffix}",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Publication material report",
        sections=[],
        markdown_path=str(report_files[0]),
        html_path=str(report_files[1]),
        fact_ledger_path=str(report_files[2]),
    )
    warning = RunWarning(
        warning_id=f"warning{suffix}",
        run_id=run.run_id,
        source_name="Fixture",
        module="market_temperature",
        message="Publication warning",
        detail=None,
        created_at=fetched_at,
    )
    coverage = ModuleCoverage(
        coverage_id=f"coverage{suffix}",
        run_id=run.run_id,
        module="market_temperature",
        status=ModuleCoverageStatus.FAILED,
        source_name="Fixture",
        message="Publication coverage",
        recorded_at=fetched_at,
    )
    return snapshot, fact, report, warning, coverage


def test_store_initializes_schema_and_round_trips_run(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )

    store.save_run(run)
    loaded = store.get_run("run-001")

    assert loaded is not None
    assert loaded.run_id == "run-001"
    assert loaded.report_type == ReportType.AFTER_CLOSE
    assert loaded.enabled_modules == ("market_indices",)


def test_create_run_is_insert_only_and_records_initial_event(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-unique",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )

    store.create_run(run)

    with pytest.raises(RunAlreadyExistsError, match="run-unique"):
        store.create_run(run)
    events = store.list_run_events("run-unique")
    assert [(event.from_status, event.to_status) for event in events] == [
        (None, RunStatus.CREATED)
    ]


def test_transition_run_updates_projection_and_appends_ordered_events(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-transitions",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)

    running = store.transition_run("run-transitions", RunStatus.RUNNING)
    completed = store.transition_run("run-transitions", RunStatus.COMPLETED)

    assert running.status == RunStatus.RUNNING
    assert running.started_at is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.completed_at is not None
    assert [event.to_status for event in store.list_run_events("run-transitions")] == [
        RunStatus.CREATED,
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
    ]


def test_transition_run_rejects_skips_and_terminal_mutation(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-invalid-transition",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)

    with pytest.raises(InvalidRunTransitionError):
        store.transition_run("run-invalid-transition", RunStatus.COMPLETED)
    store.transition_run("run-invalid-transition", RunStatus.RUNNING)
    store.transition_run("run-invalid-transition", RunStatus.FAILED)
    with pytest.raises(InvalidRunTransitionError):
        store.transition_run("run-invalid-transition", RunStatus.RUNNING)


def test_initialize_upgrades_legacy_runs_and_backfills_audit_event(tmp_path):
    database_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            create table runs (
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
            )
            """
        )
        connection.execute(
            """
            insert into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-run",
                "2026-07-01",
                "after_close",
                '["market_indices"]',
                "completed",
                "2026-07-01T07:00:00+00:00",
                "2026-07-01T07:00:01+00:00",
                "2026-07-01T07:05:00+00:00",
                0,
                None,
            ),
        )

    store = BriefingStore(database_path)
    store.initialize()

    run = store.get_run("legacy-run")
    assert run is not None
    assert run.supersedes_run_id is None
    assert [event.to_status for event in store.list_run_events("legacy-run")] == [
        RunStatus.COMPLETED
    ]


def test_initialize_upgrades_legacy_snapshot_columns(tmp_path):
    database_path = tmp_path / "legacy-snapshots.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            create table source_snapshots (
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
            )
            """
        )
        connection.execute(
            "insert into source_snapshots values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-snapshot",
                "legacy-run",
                "market_indices",
                "Legacy Provider",
                "fixture://legacy",
                "data_api",
                "2026-07-01T07:00:00+00:00",
                "application/json",
                "legacy.json",
                "{}",
            ),
        )

    store = BriefingStore(database_path)
    store.initialize()

    snapshot = store.list_snapshots("legacy-run")[0]
    assert snapshot.content_sha256 == ""
    assert snapshot.provider_name == "Legacy Provider"
    assert snapshot.license_ref is None


def test_initialize_backfills_hash_for_existing_legacy_snapshot(tmp_path):
    database_path = tmp_path / "legacy-existing-snapshot.sqlite"
    snapshot_file = write_snapshot_text(tmp_path / "legacy-existing.json", '{"legacy": true}')
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            create table source_snapshots (
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
            )
            """
        )
        connection.execute(
            "insert into source_snapshots values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-existing-snapshot",
                "legacy-run",
                "market_indices",
                "Legacy Provider",
                "fixture://legacy-existing",
                "data_api",
                "2026-07-01T07:00:00+00:00",
                "application/json",
                str(snapshot_file.path),
                "{}",
            ),
        )

    store = BriefingStore(database_path)
    store.initialize()

    snapshot = store.list_snapshots("legacy-run")[0]
    assert snapshot.content_sha256 == snapshot_file.content_sha256


def test_initialize_upgrades_legacy_facts_with_candidate_audit_links(tmp_path):
    database_path = tmp_path / "legacy-facts.sqlite"
    store = BriefingStore(database_path)
    store.initialize()
    with sqlite3.connect(database_path) as connection:
        connection.execute("alter table facts rename to facts_current")
        connection.execute(
            """
            create table facts (
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
            )
            """
        )
        connection.execute("drop table facts_current")
        connection.execute(
            """
            insert into facts values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-fact",
                "legacy-run",
                "2026-07-01",
                "after_close",
                "market_indices",
                "Legacy fact.",
                "fact",
                "Legacy Provider",
                "fixture://legacy",
                "data_api",
                None,
                "2026-07-01T07:00:00+00:00",
                "high",
                "legacy.json",
                "[]",
                "[]",
            ),
        )

    store.initialize()

    fact = store.list_facts("legacy-run")[0]
    assert fact.source_candidate_id is None
    assert fact.source_snapshot_id is None


def test_initialize_backfills_only_legacy_terminal_reports_as_published(tmp_path):
    database_path = tmp_path / "legacy-reports.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            create table runs (
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
            create table reports (
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
            """
        )
        connection.executemany(
            "insert into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "legacy-completed",
                    "2026-07-01",
                    "after_close",
                    "[]",
                    "completed",
                    "2026-07-01T08:00:00+00:00",
                    "2026-07-01T08:01:00+00:00",
                    "2026-07-01T08:05:00+00:00",
                    0,
                    None,
                ),
                (
                    "legacy-incomplete-terminal",
                    "2026-07-01",
                    "after_close",
                    "[]",
                    "completed",
                    "2026-07-01T08:30:00+00:00",
                    "2026-07-01T08:31:00+00:00",
                    None,
                    0,
                    None,
                ),
                (
                    "legacy-running",
                    "2026-07-01",
                    "after_close",
                    "[]",
                    "running",
                    "2026-07-01T09:00:00+00:00",
                    "2026-07-01T09:01:00+00:00",
                    None,
                    0,
                    None,
                ),
            ],
        )
        connection.executemany(
            "insert into reports values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "legacy-visible",
                    "legacy-completed",
                    "2026-07-01",
                    "after_close",
                    "Legacy completed report",
                    "[]",
                    "legacy-visible.md",
                    "legacy-visible.html",
                    "legacy-visible.json",
                ),
                (
                    "legacy-hidden-running",
                    "legacy-running",
                    "2026-07-01",
                    "after_close",
                    "Legacy running report",
                    "[]",
                    "legacy-running.md",
                    "legacy-running.html",
                    "legacy-running.json",
                ),
                (
                    "legacy-hidden-incomplete-terminal",
                    "legacy-incomplete-terminal",
                    "2026-07-01",
                    "after_close",
                    "Legacy incomplete terminal report",
                    "[]",
                    "legacy-incomplete.md",
                    "legacy-incomplete.html",
                    "legacy-incomplete.json",
                ),
                (
                    "legacy-hidden-orphan",
                    "legacy-missing",
                    "2026-07-01",
                    "after_close",
                    "Legacy orphan report",
                    "[]",
                    "legacy-orphan.md",
                    "legacy-orphan.html",
                    "legacy-orphan.json",
                ),
            ],
        )

    store = BriefingStore(database_path)
    store.initialize()

    assert [report.report_id for report in store.list_reports()] == ["legacy-visible"]
    assert store.get_published_report("legacy-visible").title == "Legacy completed report"
    with pytest.raises(KeyError):
        store.get_published_report("legacy-hidden-running")
    with pytest.raises(KeyError):
        store.get_published_report("legacy-hidden-incomplete-terminal")
    with pytest.raises(KeyError):
        store.get_published_report("legacy-hidden-orphan")


SCHEMA_TABLES = (
    "runs",
    "run_events",
    "source_snapshots",
    "evidence_candidates",
    "candidate_review_events",
    "facts",
    "run_warnings",
    "module_coverage",
    "reports",
    "feedback",
)


def _create_legacy_tables(connection: sqlite3.Connection) -> None:
    """最老支持形状：缺所有后续迁移新增的列。新列必须只经 _migrate_schema 补齐。"""
    connection.executescript(
        """
        create table runs (
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
        create table source_snapshots (
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
        create table evidence_candidates (
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
        create table candidate_review_events (
            event_id integer primary key autoincrement,
            candidate_id text not null,
            from_status text,
            to_status text not null,
            reviewed_at text not null,
            reviewer_id text,
            note text not null,
            approved_fact_id text
        );
        create table facts (
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
        create table run_warnings (
            warning_id text primary key,
            run_id text not null,
            source_name text not null,
            module text not null,
            message text not null,
            detail text,
            created_at text not null
        );
        create table module_coverage (
            coverage_id text primary key,
            run_id text not null,
            module text not null,
            status text not null,
            source_name text,
            message text not null,
            recorded_at text not null
        );
        create table reports (
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
        create table feedback (
            feedback_id text primary key,
            report_id text not null,
            section_id text not null,
            score integer not null,
            tags text not null,
            note text not null,
            created_at text not null
        );
        """
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return sorted(row[1] for row in connection.execute(f"pragma table_info({table})"))


def test_initialize_bring_legacy_tables_to_current_schema_columns(tmp_path):
    database_path = tmp_path / "legacy-all-tables.sqlite"
    with sqlite3.connect(database_path) as connection:
        _create_legacy_tables(connection)
        connection.execute(
            "insert into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-run",
                "2026-07-01",
                "after_close",
                '["market_indices"]',
                "completed",
                "2026-07-01T07:00:00+00:00",
                "2026-07-01T07:00:01+00:00",
                "2026-07-01T07:05:00+00:00",
                0,
                None,
            ),
        )

    fresh = sqlite3.connect(":memory:")
    fresh.executescript(SCHEMA)

    store = BriefingStore(database_path)
    store.initialize()

    with sqlite3.connect(database_path) as connection:
        for table in SCHEMA_TABLES:
            assert _table_columns(connection, table) == _table_columns(fresh, table), table


def test_candidate_is_insert_only_and_starts_with_pending_review_event(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    candidate = _candidate()

    store.save_candidate(candidate)

    with pytest.raises(CandidateAlreadyExistsError, match=candidate.candidate_id):
        store.save_candidate(candidate)
    assert store.get_candidate(candidate.candidate_id) == candidate
    assert store.candidate_review_status(candidate.candidate_id) == CandidateReviewStatus.PENDING
    events = store.list_candidate_review_events(candidate.candidate_id)
    assert [(event.from_status, event.to_status) for event in events] == [
        (None, CandidateReviewStatus.PENDING)
    ]


def test_candidate_review_appends_terminal_event_and_rejects_repeat_review(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    candidate = _candidate()
    store.save_candidate(candidate)

    approved = store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id="fact-candidate-001",
        reviewed_at=datetime(2026, 7, 2, 8, 10, tzinfo=timezone.utc),
    )

    assert approved.from_status == CandidateReviewStatus.PENDING
    assert approved.to_status == CandidateReviewStatus.APPROVED
    assert approved.approved_fact_id == "fact-candidate-001"
    assert store.candidate_review_status(candidate.candidate_id) == CandidateReviewStatus.APPROVED
    with pytest.raises(CandidateAlreadyReviewedError, match=candidate.candidate_id):
        store.review_candidate(
            candidate.candidate_id,
            CandidateReviewStatus.REJECTED,
            reviewer_id="local-maintainer",
            note="不得覆盖上一条审核。",
        )
    assert [
        event.to_status for event in store.list_candidate_review_events(candidate.candidate_id)
    ] == [CandidateReviewStatus.PENDING, CandidateReviewStatus.APPROVED]


def test_rejected_candidate_has_no_approved_fact_id(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    candidate = _candidate(candidate_id="candidate-rejected")
    store.save_candidate(candidate)

    rejected = store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.REJECTED,
        reviewer_id="local-maintainer",
        note="摘录与详情页不一致。",
    )

    assert rejected.to_status == CandidateReviewStatus.REJECTED
    assert rejected.approved_fact_id is None


def test_warnings_and_module_coverage_survive_restart_with_latest_projection(tmp_path):
    database_path = tmp_path / "briefing.sqlite"
    store = BriefingStore(database_path)
    store.initialize()
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    warning = RunWarning(
        warning_id="warning-policy-001",
        run_id="run-observability",
        source_name="示例交易所",
        module="policy_regulation",
        message="详情页检查失败",
        detail="Traceback: parser field missing",
        created_at=created_at,
    )
    pending = ModuleCoverage(
        coverage_id="coverage-policy-pending",
        run_id="run-observability",
        module="policy_regulation",
        status=ModuleCoverageStatus.PENDING_REVIEW,
        source_name="示例交易所",
        message="发现一条候选项。",
        recorded_at=created_at,
    )
    covered = ModuleCoverage(
        coverage_id="coverage-policy-covered",
        run_id="run-observability",
        module="policy_regulation",
        status=ModuleCoverageStatus.COVERED,
        source_name="示例交易所",
        message="候选项已审核。",
        recorded_at=datetime(2026, 7, 2, 8, 40, tzinfo=timezone.utc),
    )

    store.save_run_warnings([warning])
    store.save_module_coverage([pending, covered])
    reopened = BriefingStore(database_path)
    reopened.initialize()

    assert reopened.list_run_warnings("run-observability") == [warning]
    assert reopened.list_module_coverage_history("run-observability") == [pending, covered]
    assert reopened.list_module_coverage("run-observability") == [covered]


def test_warning_and_coverage_records_are_insert_only(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    warning = RunWarning(
        warning_id="warning-insert-only",
        run_id="run-insert-only",
        source_name="示例来源",
        module="sector_moves",
        message="板块覆盖缺失",
        detail=None,
        created_at=created_at,
    )
    coverage = ModuleCoverage(
        coverage_id="coverage-insert-only",
        run_id="run-insert-only",
        module="sector_moves",
        status=ModuleCoverageStatus.UNSUPPORTED,
        source_name=None,
        message="验证版暂未支持。",
        recorded_at=created_at,
    )
    store.save_run_warnings([warning])
    store.save_module_coverage([coverage])

    with pytest.raises(PublishedRecordExistsError):
        store.save_run_warnings([warning])
    with pytest.raises(PublishedRecordExistsError):
        store.save_module_coverage([coverage])


def test_store_closes_connections_after_operations(tmp_path):
    database_path = tmp_path / "briefing.sqlite"
    store = TrackingStore(database_path)
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    TrackingConnection.close_count = 0

    store.initialize()
    store.save_run(run)
    database_path.unlink()

    assert TrackingConnection.close_count == 2
    assert not database_path.exists()


def test_store_round_trips_snapshot_fact_and_report(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    snapshot = RawSnapshot(
        snapshot_id="snapshot-001",
        run_id="run-001",
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://indices",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path="data/raw/2026-07-02/run-001/indices.json",
        content_sha256="b" * 64,
        provider_name="Fixture",
        license_ref="fixture:test-data",
        metadata={"rows": 4, "symbols": ["000001.SH"]},
    )
    fact = AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="Shanghai Composite closed higher.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://indices",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=snapshot.raw_path,
        derived_from_fact_ids=["source-fact-001"],
        used_in_sections=["market_indices"],
    )
    report = Report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="After-close briefing",
        sections=[
            ReportSection(
                section_id="market_indices",
                title="Index performance",
                body="Shanghai Composite closed higher. [fact-001]",
                fact_ids=["fact-001"],
                status="ok",
                fact_lines=[
                    FactLine(
                        fact_id="fact-001",
                        classification=FactClassification.FACT,
                        claim="Shanghai Composite closed higher.",
                        derived_from_fact_ids=["source-fact-001"],
                    )
                ],
            )
        ],
        markdown_path="reports/2026-07-02/after_close/briefing.md",
        html_path="reports/2026-07-02/after_close/briefing.html",
        fact_ledger_path="reports/2026-07-02/after_close/fact_ledger.json",
    )

    store.save_snapshot(snapshot)
    store.save_facts([fact])
    store.save_report(report)

    loaded_snapshot = store.list_snapshots("run-001")[0]
    loaded_fact = store.list_facts("run-001")[0]
    loaded_report = store.get_report("report-001")

    assert loaded_snapshot.snapshot_id == "snapshot-001"
    assert loaded_snapshot.content_sha256 == "b" * 64
    assert loaded_snapshot.provider_name == "Fixture"
    assert loaded_snapshot.license_ref == "fixture:test-data"
    assert loaded_snapshot.metadata["symbols"] == ("000001.SH",)
    assert loaded_fact.fact_id == "fact-001"
    assert loaded_fact.derived_from_fact_ids == ("source-fact-001",)
    assert loaded_fact.used_in_sections == ("market_indices",)
    assert loaded_report.title == "After-close briefing"
    assert loaded_report.sections[0].fact_ids == ("fact-001",)
    assert loaded_report.sections[0].fact_lines[0].fact_id == "fact-001"
    assert loaded_report.sections[0].fact_lines[0].classification == FactClassification.FACT
    assert loaded_report.sections[0].fact_lines[0].derived_from_fact_ids == ("source-fact-001",)


def test_published_snapshots_facts_and_reports_are_insert_only(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    snapshot_file = write_snapshot_text(tmp_path / "snapshot.json", "{}")
    snapshot = RawSnapshot(
        snapshot_id="snapshot-insert-only",
        run_id="run-insert-only",
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://insert-only",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    fact = AtomicFact(
        fact_id="fact-insert-only",
        run_id="run-insert-only",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="Insert-only fact.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://insert-only",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=str(snapshot_file.path),
    )
    report = Report(
        report_id="report-insert-only",
        run_id="run-insert-only",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Insert-only report",
        sections=[],
        markdown_path=str(tmp_path / "briefing.md"),
        html_path=str(tmp_path / "briefing.html"),
        fact_ledger_path=str(tmp_path / "facts.json"),
    )

    store.save_snapshot(snapshot)
    store.save_facts([fact])
    store.save_report(report)

    with pytest.raises(PublishedRecordExistsError):
        store.save_snapshot(snapshot)
    with pytest.raises(PublishedRecordExistsError):
        store.save_facts([fact])
    with pytest.raises(PublishedRecordExistsError):
        store.save_report(report)


def test_publish_run_bundle_rolls_back_all_visible_records_on_conflict(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    run = Run.create(
        run_id="run-bundle",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot_file = write_snapshot_text(tmp_path / "snapshot-bundle.json", "{}")
    snapshot = RawSnapshot(
        snapshot_id="snapshot-bundle",
        run_id=run.run_id,
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://bundle",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    fact = AtomicFact(
        fact_id="fact-bundle-conflict",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        module="market_indices",
        claim="Bundle fact.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://bundle",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=str(snapshot_file.path),
    )
    conflicting_fact = replace(fact, run_id="other-run", claim="Existing conflict.")
    store.save_facts([conflicting_fact])
    report = Report(
        report_id="report-bundle",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Bundle report",
        sections=[],
        markdown_path=str(tmp_path / "bundle.md"),
        html_path=str(tmp_path / "bundle.html"),
        fact_ledger_path=str(tmp_path / "bundle.json"),
    )
    for path in (report.markdown_path, report.html_path, report.fact_ledger_path):
        tmp_path.joinpath(path).write_text("bundle artifact", encoding="utf-8")

    with pytest.raises(PublishedRecordExistsError):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[fact],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_snapshots(run.run_id) == []
    assert store.list_facts(run.run_id) == []
    with pytest.raises(KeyError):
        store.get_report(report.report_id)
    assert store.get_run(run.run_id).status == RunStatus.RUNNING
    assert [event.to_status for event in store.list_run_events(run.run_id)] == [
        RunStatus.CREATED,
        RunStatus.RUNNING,
    ]


@pytest.mark.parametrize(
    "record_kind",
    ["snapshot", "fact", "report", "warning", "coverage"],
)
def test_publish_bundle_rejects_preexisting_normal_ledger_records_for_run(
    tmp_path,
    record_kind,
):
    store = BriefingStore(tmp_path / f"{record_kind}.sqlite")
    store.initialize()
    run = Run.create(
        run_id=f"run-preexisting-{record_kind}",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, warning, coverage = _publication_material(
        tmp_path,
        run,
        suffix=f"-{record_kind}",
    )
    writers = {
        "snapshot": lambda: store.save_snapshot(snapshot),
        "fact": lambda: store.save_facts([fact]),
        "report": lambda: store.save_report(replace(report, report_id=f"staged-{record_kind}")),
        "warning": lambda: store.save_run_warnings([warning]),
        "coverage": lambda: store.save_module_coverage([coverage]),
    }
    writers[record_kind]()

    with pytest.raises(InvalidPublicationBundleError, match="already has normal ledger records"):
        store.publish_run_bundle(
            snapshots=[],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.get_run(run.run_id).status == RunStatus.RUNNING
    assert store.list_reports() == []


def test_terminal_run_rejects_all_compatibility_ledger_appends(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-terminal-append",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    _, _, report, _, _ = _publication_material(tmp_path, run, suffix="-published")
    store.publish_run_bundle(
        snapshots=[],
        facts=[],
        report=report,
        target_status=RunStatus.COMPLETED,
    )
    snapshot, fact, extra_report, warning, coverage = _publication_material(
        tmp_path,
        run,
        suffix="-late",
    )

    with pytest.raises(PublishedRecordExistsError):
        store.save_snapshot(snapshot)
    with pytest.raises(PublishedRecordExistsError):
        store.save_facts([fact])
    with pytest.raises(PublishedRecordExistsError):
        store.save_report(extra_report)
    with pytest.raises(PublishedRecordExistsError):
        store.save_run_warnings([warning])
    with pytest.raises(PublishedRecordExistsError):
        store.save_module_coverage([coverage])

    assert store.list_snapshots(run.run_id) == []
    assert store.list_facts(run.run_id) == []
    assert store.list_run_warnings(run.run_id) == []
    assert store.list_module_coverage(run.run_id) == []
    assert [item.report_id for item in store.list_reports()] == [report.report_id]


def test_normal_report_queries_hide_orphan_and_nonterminal_records(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-not-published",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    report = Report(
        report_id="report-not-published",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Not published",
        sections=[],
        markdown_path=str(tmp_path / "not-published.md"),
        html_path=str(tmp_path / "not-published.html"),
        fact_ledger_path=str(tmp_path / "not-published.json"),
    )
    orphan = replace(
        report,
        report_id="report-orphan",
        run_id="run-missing",
        title="Orphan report",
    )
    store.save_report(report)
    store.save_report(orphan)

    assert store.get_report(report.report_id) == report
    assert store.get_report(orphan.report_id) == orphan
    assert store.list_reports() == []
    assert store.latest_report() is None
    with pytest.raises(KeyError):
        store.get_published_report(report.report_id)
    with pytest.raises(KeyError):
        store.get_published_report(orphan.report_id)


def test_publish_bundle_rejects_tampered_snapshot_before_visibility(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-tampered-before-publish",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot_file = write_snapshot_text(tmp_path / "tampered.json", "original")
    snapshot = RawSnapshot(
        snapshot_id="snapshot-tampered-before-publish",
        run_id=run.run_id,
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://tampered",
        source_type=SourceType.DATA_API,
        fetched_at=datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc),
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    report_files = [tmp_path / name for name in ("tampered.md", "tampered.html", "tampered-ledger.json")]
    for report_file in report_files:
        report_file.write_text("report", encoding="utf-8")
    report = Report(
        report_id="report-tampered-before-publish",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Tampered report",
        sections=[],
        markdown_path=str(report_files[0]),
        html_path=str(report_files[1]),
        fact_ledger_path=str(report_files[2]),
    )
    snapshot_file.path.write_text("tampered", encoding="utf-8")

    with pytest.raises(InvalidPublicationBundleError, match=snapshot.snapshot_id):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_snapshots(run.run_id) == []
    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_rejects_cross_run_material_and_warning_status_mismatch(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-bundle-preflight",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    report_files = [tmp_path / name for name in ("preflight.md", "preflight.html", "preflight.json")]
    for report_file in report_files:
        report_file.write_text("report", encoding="utf-8")
    report = Report(
        report_id="report-bundle-preflight",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Preflight report",
        sections=[],
        markdown_path=str(report_files[0]),
        html_path=str(report_files[1]),
        fact_ledger_path=str(report_files[2]),
    )
    snapshot_file = write_snapshot_text(tmp_path / "preflight-snapshot.json", "{}")
    wrong_run_snapshot = RawSnapshot(
        snapshot_id="snapshot-wrong-run",
        run_id="other-run",
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://wrong-run",
        source_type=SourceType.DATA_API,
        fetched_at=datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc),
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    warning = RunWarning(
        warning_id="warning-preflight",
        run_id=run.run_id,
        source_name="Fixture",
        module="market_temperature",
        message="Missing temperature",
        detail=None,
        created_at=datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(InvalidPublicationBundleError, match="snapshot-wrong-run"):
        store.publish_run_bundle(
            snapshots=[wrong_run_snapshot],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )
    with pytest.raises(InvalidPublicationBundleError, match="completed_with_warnings"):
        store.publish_run_bundle(
            snapshots=[],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
            warnings=[warning],
        )

    assert store.list_reports() == []
    assert store.list_run_warnings(run.run_id) == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_rejects_fact_derived_from_missing_bundle_fact(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-missing-derivation",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-missing-derivation",
    )
    inference = replace(
        fact,
        classification=FactClassification.INFERENCE,
        derived_from_fact_ids=("fact-not-in-bundle",),
    )

    with pytest.raises(InvalidPublicationBundleError, match="fact-not-in-bundle"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[inference],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_facts(run.run_id) == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


@pytest.mark.parametrize(
    ("candidate_setup", "expected_error"),
    [
        ("missing", "candidate-missing"),
        ("pending", "is not approved"),
        ("wrong_fact", "does not approve fact"),
        ("wrong_snapshot", "does not match snapshot"),
    ],
)
def test_publish_bundle_rejects_invalid_candidate_audit_links(
    tmp_path,
    candidate_setup,
    expected_error,
):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-candidate-link",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-candidate-link",
    )
    candidate_id = "candidate-missing"

    if candidate_setup != "missing":
        candidate_id = f"candidate-{candidate_setup}"
        candidate = replace(
            _candidate(candidate_id),
            run_id=run.run_id,
            module=snapshot.module,
            excerpt=fact.claim,
            suggested_classification=fact.classification,
            snapshot_id=(
                "snapshot-other" if candidate_setup == "wrong_snapshot" else snapshot.snapshot_id
            ),
        )
        store.save_candidate(candidate)
        if candidate_setup != "pending":
            store.review_candidate(
                candidate.candidate_id,
                CandidateReviewStatus.APPROVED,
                reviewer_id="local-maintainer",
                note="已核对详情页。",
                approved_fact_id=(
                    "fact-other" if candidate_setup == "wrong_fact" else fact.fact_id
                ),
            )

    linked_fact = replace(
        fact,
        source_candidate_id=candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
    )

    with pytest.raises(InvalidPublicationBundleError, match=expected_error):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[linked_fact],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_facts(run.run_id) == []
    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_requires_every_candidate_review_to_be_resolved(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-pending-candidate",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, _, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-pending-candidate",
    )
    store.save_candidate(
        replace(
            _candidate("candidate-pending-publication"),
            run_id=run.run_id,
            module=snapshot.module,
            snapshot_id=snapshot.snapshot_id,
        )
    )

    with pytest.raises(InvalidPublicationBundleError, match="is not resolved"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_accepts_complete_approved_candidate_chain(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-approved-candidate",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-approved-candidate",
    )
    candidate = replace(
        _candidate("candidate-approved-publication"),
        run_id=run.run_id,
        module=snapshot.module,
        snapshot_id=snapshot.snapshot_id,
        excerpt=fact.claim,
        suggested_classification=fact.classification,
    )
    store.save_candidate(candidate)
    store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id=fact.fact_id,
    )
    linked_fact = replace(
        fact,
        source_candidate_id=candidate.candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
    )

    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[linked_fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )

    assert store.get_run(run.run_id).status == RunStatus.COMPLETED
    assert store.list_facts(run.run_id) == [linked_fact]


@pytest.mark.parametrize(
    "fact_change",
    [
        {"module": "major_news"},
        {"claim": "与候选摘录不同的事实。"},
        {"classification": FactClassification.OPINION},
    ],
)
def test_publish_bundle_rejects_candidate_fact_content_mismatch(tmp_path, fact_change):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-candidate-content",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-candidate-content",
    )
    candidate = replace(
        _candidate("candidate-content"),
        run_id=run.run_id,
        module=snapshot.module,
        snapshot_id=snapshot.snapshot_id,
        excerpt=fact.claim,
        suggested_classification=fact.classification,
    )
    store.save_candidate(candidate)
    store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id=fact.fact_id,
    )
    linked_fact = replace(
        fact,
        source_candidate_id=candidate.candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
        **fact_change,
    )

    with pytest.raises(InvalidPublicationBundleError, match="does not match candidate"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[linked_fact],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_requires_approved_candidate_fact_in_bundle(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-candidate-fact-missing",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-candidate-fact-missing",
    )
    candidate = replace(
        _candidate("candidate-fact-missing"),
        run_id=run.run_id,
        module=snapshot.module,
        snapshot_id=snapshot.snapshot_id,
    )
    store.save_candidate(candidate)
    store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id=fact.fact_id,
    )

    with pytest.raises(InvalidPublicationBundleError, match="approved fact"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_terminal_run_rejects_candidate_append(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-terminal-candidate",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    _, _, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-terminal-candidate",
    )
    store.publish_run_bundle(
        snapshots=[],
        facts=[],
        report=report,
        target_status=RunStatus.COMPLETED,
    )

    with pytest.raises(PublishedRecordExistsError, match="terminal"):
        store.save_candidate(
            replace(
                _candidate("candidate-after-terminal"),
                run_id=run.run_id,
            )
        )

    with pytest.raises(KeyError):
        store.get_candidate("candidate-after-terminal")


def test_publish_bundle_rejects_missing_fact_referenced_only_by_fact_line(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-missing-fact-line",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    _, _, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-missing-fact-line",
    )
    report = replace(
        report,
        sections=(
            ReportSection(
                section_id="market_indices",
                title="Index performance",
                body="Structured reference only.",
                fact_ids=(),
                status="ok",
                fact_lines=(
                    FactLine(
                        fact_id="fact-only-in-line",
                        classification=FactClassification.FACT,
                        claim="Missing structured fact.",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(InvalidPublicationBundleError, match="fact-only-in-line"):
        store.publish_run_bundle(
            snapshots=[],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_publish_bundle_rejects_fact_line_with_unledgered_derivation(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-mismatched-fact-line",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-mismatched-fact-line",
    )
    report = replace(
        report,
        sections=(
            ReportSection(
                section_id="market_indices",
                title="Index performance",
                body="Mismatched structured line.",
                fact_ids=(fact.fact_id,),
                status="ok",
                fact_lines=(
                    FactLine(
                        fact_id=fact.fact_id,
                        classification=fact.classification,
                        claim=fact.claim,
                        derived_from_fact_ids=("missing-fact",),
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(InvalidPublicationBundleError, match="does not match fact ledger"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[fact],
            report=report,
            target_status=RunStatus.COMPLETED,
        )

    assert store.list_reports() == []
    assert store.get_run(run.run_id).status == RunStatus.RUNNING


def test_audit_integrity_rejects_missing_or_tampered_published_snapshot(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    run = Run.create(
        run_id="run-integrity",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot_file = write_snapshot_text(tmp_path / "integrity.json", "original")
    snapshot = RawSnapshot(
        snapshot_id="snapshot-integrity",
        run_id=run.run_id,
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://integrity",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="Fixture",
    )
    report_files = [tmp_path / name for name in ("briefing.md", "briefing.html", "facts.json")]
    for report_file in report_files:
        report_file.write_text("report", encoding="utf-8")
    report = Report(
        report_id="report-integrity",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="Integrity report",
        sections=[],
        markdown_path=str(report_files[0]),
        html_path=str(report_files[1]),
        fact_ledger_path=str(report_files[2]),
    )
    warning = RunWarning(
        warning_id="warning-integrity",
        run_id=run.run_id,
        source_name="Fixture",
        module="market_temperature",
        message="市场温度缺失",
        detail="diagnostic detail",
        created_at=fetched_at,
    )
    coverage = ModuleCoverage(
        coverage_id="coverage-integrity",
        run_id=run.run_id,
        module="market_temperature",
        status=ModuleCoverageStatus.FAILED,
        source_name="Fixture",
        message="市场温度未覆盖。",
        recorded_at=fetched_at,
    )
    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[],
        report=report,
        target_status=RunStatus.COMPLETED_WITH_WARNINGS,
        warnings=[warning],
        module_coverage=[coverage],
    )

    assert store.get_run(run.run_id).warning_count == 1
    assert store.list_run_warnings(run.run_id) == [warning]
    assert store.list_module_coverage(run.run_id) == [coverage]
    store.assert_report_integrity(report.report_id)
    snapshot_file.path.write_text("tampered", encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="snapshot-integrity"):
        store.assert_report_integrity(report.report_id)


def test_publish_run_bundle_persists_report_artifact_hashes(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-artifact-hashes",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, warning, coverage = _publication_material(tmp_path, run)
    Path(report.markdown_path).write_text("distinct markdown artifact", encoding="utf-8")

    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )

    with sqlite3.connect(store.database_path) as connection:
        row = connection.execute(
            "select markdown_sha256, html_sha256 from reports where report_id = ?",
            (report.report_id,),
        ).fetchone()
    assert row[0] == sha256(Path(report.markdown_path).read_bytes()).hexdigest()
    assert row[1] == sha256(Path(report.html_path).read_bytes()).hexdigest()
    assert row[0] != row[1]


def _publish_report_with_artifacts(tmp_path, run_id: str) -> tuple[BriefingStore, Report]:
    store = BriefingStore(tmp_path / f"briefing-{run_id}.sqlite")
    store.initialize()
    run = Run.create(
        run_id=run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, warning, coverage = _publication_material(tmp_path, run)
    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )
    return store, report


def test_audit_integrity_rejects_tampered_published_markdown(tmp_path):
    store, report = _publish_report_with_artifacts(tmp_path, "run-tamper-md")
    store.assert_report_integrity(report.report_id)
    Path(report.markdown_path).write_text("tampered after publish", encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="markdown"):
        store.assert_report_integrity(report.report_id)


def test_audit_integrity_rejects_tampered_published_html(tmp_path):
    store, report = _publish_report_with_artifacts(tmp_path, "run-tamper-html")
    store.assert_report_integrity(report.report_id)
    Path(report.html_path).write_text("<p>tampered</p>", encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="html"):
        store.assert_report_integrity(report.report_id)


def test_audit_integrity_rejects_missing_report_artifact_hash(tmp_path):
    store, report = _publish_report_with_artifacts(tmp_path, "run-missing-hash")
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "update reports set markdown_sha256 = '' where report_id = ?",
            (report.report_id,),
        )

    with pytest.raises(AuditIntegrityError, match="markdown"):
        store.assert_report_integrity(report.report_id)


def test_publish_run_bundle_rejects_paths_outside_trusted_roots(tmp_path):
    store = BriefingStore(
        tmp_path / "briefing.sqlite",
        trusted_roots=(tmp_path / "trusted" / "raw", tmp_path / "trusted" / "reports"),
    )
    store.initialize()
    run = Run.create(
        run_id="run-untrusted",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, warning, coverage = _publication_material(tmp_path / "outside", run)

    with pytest.raises(InvalidPublicationBundleError, match="outside the trusted roots"):
        store.publish_run_bundle(
            snapshots=[snapshot],
            facts=[fact],
            report=report,
            target_status=RunStatus.COMPLETED,
        )


def test_publish_run_bundle_accepts_paths_inside_trusted_roots(tmp_path):
    trusted_root = tmp_path / "trusted"
    store = BriefingStore(
        tmp_path / "briefing.sqlite",
        trusted_roots=(trusted_root / "raw", trusted_root / "reports"),
    )
    store.initialize()
    run = Run.create(
        run_id="run-trusted",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, warning, coverage = _publication_material(
        trusted_root / "raw", run
    )
    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )

    assert store.get_run(run.run_id).status == RunStatus.COMPLETED


def test_initialize_backfills_report_artifact_hashes_for_existing_legacy_files(tmp_path):
    database_path = tmp_path / "legacy-report-hashes.sqlite"
    markdown_file = tmp_path / "legacy-visible.md"
    html_file = tmp_path / "legacy-visible.html"
    markdown_file.write_text("legacy markdown artifact", encoding="utf-8")
    html_file.write_text("legacy html artifact", encoding="utf-8")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            create table runs (
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
            create table reports (
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
            """
        )
        connection.execute(
            "insert into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-completed",
                "2026-07-01",
                "after_close",
                "[]",
                "completed",
                "2026-07-01T08:00:00+00:00",
                "2026-07-01T08:01:00+00:00",
                "2026-07-01T08:05:00+00:00",
                0,
                None,
            ),
        )
        connection.executemany(
            "insert into reports values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "legacy-visible",
                    "legacy-completed",
                    "2026-07-01",
                    "after_close",
                    "Legacy visible report",
                    "[]",
                    str(markdown_file),
                    str(html_file),
                    "legacy-visible.json",
                ),
                (
                    "legacy-missing-files",
                    "legacy-completed",
                    "2026-07-01",
                    "after_close",
                    "Legacy report with missing artifacts",
                    "[]",
                    str(tmp_path / "absent.md"),
                    str(tmp_path / "absent.html"),
                    "absent.json",
                ),
            ],
        )

    store = BriefingStore(database_path)
    store.initialize()

    with sqlite3.connect(database_path) as connection:
        rows = dict(
            (row[0], (row[1], row[2]))
            for row in connection.execute(
                "select report_id, markdown_sha256, html_sha256 from reports"
            )
        )
    assert rows["legacy-visible"] == (
        sha256(markdown_file.read_bytes()).hexdigest(),
        sha256(html_file.read_bytes()).hexdigest(),
    )
    assert rows["legacy-missing-files"] == ("", "")


def test_audit_integrity_rejects_tampered_candidate_approval_link(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-candidate-integrity",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    snapshot, fact, report, _, _ = _publication_material(
        tmp_path,
        run,
        suffix="-candidate-integrity",
    )
    candidate = replace(
        _candidate("candidate-integrity"),
        run_id=run.run_id,
        module=snapshot.module,
        snapshot_id=snapshot.snapshot_id,
        excerpt=fact.claim,
        suggested_classification=fact.classification,
    )
    store.save_candidate(candidate)
    store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id=fact.fact_id,
    )
    linked_fact = replace(
        fact,
        source_candidate_id=candidate.candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
    )
    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[linked_fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )
    store.assert_report_integrity(report.report_id)

    with store.connection() as connection:
        connection.execute(
            """
            update candidate_review_events
            set approved_fact_id = ?
            where candidate_id = ? and to_status = ?
            """,
            (
                "fact-tampered",
                candidate.candidate_id,
                CandidateReviewStatus.APPROVED.value,
            ),
        )

    with pytest.raises(AuditIntegrityError, match=candidate.candidate_id):
        store.assert_report_integrity(report.report_id)


def test_get_report_loads_legacy_sections_without_fact_lines(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    legacy_sections = (
        '[{"section_id":"market_indices","title":"Market indices",'
        '"body":"Legacy body [fact-001]","fact_ids":["fact-001"],"status":"ok"}]'
    )
    with store.connection() as connection:
        connection.execute(
            """
            insert into reports (
                report_id, run_id, report_date, report_type, title,
                sections, markdown_path, html_path, fact_ledger_path
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "report-legacy",
                "run-legacy",
                "2026-07-02",
                ReportType.AFTER_CLOSE.value,
                "Legacy report",
                legacy_sections,
                "reports/legacy.md",
                "reports/legacy.html",
                "reports/legacy.json",
            ),
        )

    report = store.get_report("report-legacy")

    assert report.sections[0].body == "Legacy body [fact-001]"
    assert report.sections[0].fact_ids == ("fact-001",)
    assert report.sections[0].fact_lines == ()


def test_get_report_raises_key_error_for_unknown_report(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()

    with pytest.raises(KeyError):
        store.get_report("missing-report")


def test_latest_report_uses_run_timestamp_when_report_dates_match(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    older_run = Run.create(
        run_id="z-older",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    newer_run = Run.create(
        run_id="a-newer",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    older_run = replace(older_run, created_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc))
    newer_run = replace(newer_run, created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc))
    older_report = Report(
        report_id="report-z-older",
        run_id=older_run.run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Older report",
        sections=[
            ReportSection("market_indices", "Market indices", "Older", [], "ok"),
        ],
        markdown_path=str(tmp_path / "older.md"),
        html_path=str(tmp_path / "older.html"),
        fact_ledger_path=str(tmp_path / "older.json"),
    )
    newer_report = Report(
        report_id="report-a-newer",
        run_id=newer_run.run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Newer report",
        sections=[
            ReportSection("market_indices", "Market indices", "Newer", [], "ok"),
        ],
        markdown_path=str(tmp_path / "newer.md"),
        html_path=str(tmp_path / "newer.html"),
        fact_ledger_path=str(tmp_path / "newer.json"),
    )

    for report in (older_report, newer_report):
        for path in (report.markdown_path, report.html_path, report.fact_ledger_path):
            tmp_path.joinpath(path).write_text("report artifact", encoding="utf-8")
    for run, report in ((older_run, older_report), (newer_run, newer_report)):
        store.create_run(run)
        store.transition_run(run.run_id, RunStatus.RUNNING)
        store.publish_run_bundle(
            snapshots=[],
            facts=[],
            report=report,
            target_status=RunStatus.COMPLETED,
        )
    with store.connection() as connection:
        connection.execute(
            "update runs set completed_at = ? where run_id = ?",
            ("2026-07-02T08:05:00+00:00", older_run.run_id),
        )
        connection.execute(
            "update runs set completed_at = ? where run_id = ?",
            ("2026-07-02T09:05:00+00:00", newer_run.run_id),
        )

    reports = store.list_reports()

    assert [report.report_id for report in reports] == ["report-a-newer", "report-z-older"]
    assert store.latest_report() == newer_report


def test_build_report_paths_uses_date_type_and_run_id(tmp_path):
    paths = build_report_paths(
        reports_dir=tmp_path / "reports",
        report_date="2026-07-02",
        report_type=ReportType.PRE_OPEN_UPDATE,
        run_id="run-abc",
    )

    assert paths.report_dir == tmp_path / "reports" / "2026-07-02" / "pre_open_update" / "run-abc"
    assert paths.markdown_path == paths.report_dir / "briefing.md"
    assert paths.html_path == paths.report_dir / "briefing.html"
    assert paths.fact_ledger_path == paths.report_dir / "fact_ledger.json"
