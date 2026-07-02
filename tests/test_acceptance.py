from datetime import datetime, timezone
from pathlib import Path

from market_briefing.config import AppConfig
from market_briefing.domain import FeedbackEntry, ReportType
from market_briefing.feedback import summarize_feedback
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore


def test_fixture_reports_and_feedback_complete_acceptance_smoke(tmp_path):
    config = AppConfig(
        database_path=tmp_path / "briefing.sqlite",
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        generation_provider="template",
        report_modules={
            ReportType.AFTER_CLOSE: {
                "market_indices": True,
                "policy_regulation": True,
                "risk_points": True,
            },
            ReportType.PRE_OPEN_UPDATE: {
                "overnight_context": True,
                "today_watchpoints": True,
            },
        },
    )
    store = BriefingStore(config.database_path)
    store.initialize()

    after_close = run_fixture_pipeline(
        PipelineRequest(
            run_id="acceptance-after-close",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )
    pre_open = run_fixture_pipeline(
        PipelineRequest(
            run_id="acceptance-pre-open",
            report_date="2026-07-03",
            report_type=ReportType.PRE_OPEN_UPDATE,
            fixture_path=Path("tests/fixtures/pre_open_sources.json"),
        ),
        config=config,
        store=store,
    )

    feedback = FeedbackEntry(
        feedback_id="acceptance-feedback-001",
        report_id=after_close.report.report_id,
        section_id="risk_points",
        score=4,
        tags=("insufficient_risk",),
        note="Acceptance note: make risk signals more explicit.",
        created_at=datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc),
    )
    store.save_feedback(feedback)

    assert Path(after_close.report.markdown_path).exists()
    assert Path(after_close.report.html_path).exists()
    assert Path(after_close.report.fact_ledger_path).exists()
    assert Path(pre_open.report.markdown_path).exists()
    assert Path(pre_open.report.html_path).exists()
    assert Path(pre_open.report.fact_ledger_path).exists()
    assert len(store.list_snapshots("acceptance-after-close")) == 3
    assert len(store.list_facts("acceptance-after-close")) == 4
    assert len(store.list_snapshots("acceptance-pre-open")) == 2
    assert len(store.list_facts("acceptance-pre-open")) == 2
    assert feedback.note in summarize_feedback(
        store.list_feedback(after_close.report.report_id)
    )
