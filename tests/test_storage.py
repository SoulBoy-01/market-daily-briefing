from dataclasses import replace
from datetime import datetime, timezone
import sqlite3

import pytest

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FactLine,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    SourceType,
)
from market_briefing.storage import (
    BriefingStore,
    InvalidRunTransitionError,
    RunAlreadyExistsError,
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
    older_run = replace(
        older_run,
        created_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 2, 8, 5, tzinfo=timezone.utc),
    )
    newer_run = replace(
        newer_run,
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 2, 9, 5, tzinfo=timezone.utc),
    )
    older_report = Report(
        report_id="report-z-older",
        run_id=older_run.run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Older report",
        sections=[
            ReportSection("market_indices", "Market indices", "Older", [], "ok"),
        ],
        markdown_path="reports/older.md",
        html_path="reports/older.html",
        fact_ledger_path="reports/older.json",
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
        markdown_path="reports/newer.md",
        html_path="reports/newer.html",
        fact_ledger_path="reports/newer.json",
    )

    store.save_run(older_run)
    store.save_run(newer_run)
    store.save_report(older_report)
    store.save_report(newer_report)

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
