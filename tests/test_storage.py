from dataclasses import replace
from datetime import datetime, timezone
import sqlite3

import pytest

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    SourceType,
)
from market_briefing.storage import BriefingStore, build_report_paths


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
                "market_indices",
                "Index performance",
                "Shanghai Composite closed higher. [fact-001]",
                ["fact-001"],
                "ok",
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
    assert loaded_snapshot.metadata["symbols"] == ("000001.SH",)
    assert loaded_fact.fact_id == "fact-001"
    assert loaded_fact.derived_from_fact_ids == ("source-fact-001",)
    assert loaded_fact.used_in_sections == ("market_indices",)
    assert loaded_report.title == "After-close briefing"
    assert loaded_report.sections[0].fact_ids == ("fact-001",)


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
