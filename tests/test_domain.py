from datetime import datetime, timezone

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FeedbackEntry,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    SourceType,
)


def test_raw_snapshot_can_be_serialized():
    snapshot = RawSnapshot(
        snapshot_id="snapshot-001",
        run_id="run-001",
        module="market_indices",
        source_name="Fixture Market Data",
        source_url="fixture://market/indices",
        source_type=SourceType.DATA_API,
        fetched_at=datetime(2026, 7, 2, 15, 10, tzinfo=timezone.utc),
        content_type="application/json",
        raw_path="data/raw/2026-07-02/run-001/indices.json",
        metadata={"row_count": 3},
    )

    payload = snapshot.to_record()

    assert payload["snapshot_id"] == "snapshot-001"
    assert payload["source_type"] == "data_api"
    assert payload["fetched_at"] == "2026-07-02T15:10:00+00:00"
    assert payload["metadata"] == {"row_count": 3}


def test_atomic_fact_requires_supported_classification_and_can_be_serialized():
    fact = AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="涓婅瘉鎸囨暟鏀舵定 0.5%銆?",
        classification=FactClassification.FACT,
        source_name="Fixture Market Data",
        source_url="fixture://market/indices",
        source_type=SourceType.DATA_API,
        published_at=datetime(2026, 7, 2, 15, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 2, 15, 10, tzinfo=timezone.utc),
        confidence="high",
        raw_snapshot_path="data/raw/2026-07-02/run-001/indices.json",
        derived_from_fact_ids=[],
        used_in_sections=["market_indices"],
    )

    payload = fact.to_record()

    assert payload["fact_id"] == "fact-001"
    assert payload["classification"] == "fact"
    assert payload["report_type"] == "after_close"
    assert payload["source_type"] == "data_api"


def test_report_collects_all_fact_ids_from_sections():
    section = ReportSection(
        section_id="market_indices",
        title="鎸囨暟琛ㄧ幇",
        body="涓婅瘉鎸囨暟鏀舵定銆俒fact-001]",
        fact_ids=["fact-001"],
        status="ok",
    )
    report = Report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="A鑲＄洏鍚庣畝鎶?",
        sections=[section],
        markdown_path="reports/2026-07-02/after_close/briefing.md",
        html_path="reports/2026-07-02/after_close/briefing.html",
        fact_ledger_path="reports/2026-07-02/after_close/fact_ledger.json",
    )

    assert report.all_fact_ids() == {"fact-001"}


def test_feedback_entry_summarizes_tags_and_note():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk", "unclear_citation"],
        note="椋庨櫓鐐硅鏇存槑纭紩鐢ㄤ簨瀹炪€?",
        created_at=datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc),
    )

    assert (
        entry.summary_line()
        == "risk_points: score=4; tags=insufficient_risk,unclear_citation; note=椋庨櫓鐐硅鏇存槑纭紩鐢ㄤ簨瀹炪€?"
    )


def test_run_defaults_to_created_status_and_tracks_modules():
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.PRE_OPEN_UPDATE,
        enabled_modules=["overnight_context", "today_watchpoints"],
    )

    assert run.status == RunStatus.CREATED
    assert run.enabled_modules == ["overnight_context", "today_watchpoints"]
