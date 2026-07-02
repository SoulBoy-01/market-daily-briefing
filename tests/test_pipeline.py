from pathlib import Path

from market_briefing.config import AppConfig
from market_briefing.domain import ReportType
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore


def _config(tmp_path):
    return AppConfig(
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


def test_fixture_pipeline_generates_auditable_after_close_report(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    result = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-after-close-001",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )

    assert result.report.report_id == "report-run-after-close-001"
    assert Path(result.report.markdown_path).exists()
    assert Path(result.report.html_path).exists()
    assert Path(result.report.fact_ledger_path).exists()
    assert len(store.list_snapshots("run-after-close-001")) == 3
    assert len(store.list_facts("run-after-close-001")) == 4
    assert "A股盘后简报 2026-07-02" in Path(result.report.markdown_path).read_text(
        encoding="utf-8"
    )


def test_fixture_pipeline_generates_pre_open_report(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    result = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-pre-open-001",
            report_date="2026-07-03",
            report_type=ReportType.PRE_OPEN_UPDATE,
            fixture_path=Path("tests/fixtures/pre_open_sources.json"),
        ),
        config=config,
        store=store,
    )

    assert result.report.title == "A股早盘补充 2026-07-03"
    assert len(store.list_facts("run-pre-open-001")) == 2
