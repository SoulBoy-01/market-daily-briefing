import json
import sys
from pathlib import Path

import pytest

from market_briefing.config import AppConfig
from market_briefing.domain import ReportType, RunStatus
from market_briefing.pipeline import PipelineRequest, main, run_fixture_pipeline
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


def _bad_fixture(tmp_path):
    fixture_path = tmp_path / "bad_sources.json"
    fixture_path.write_text(
        json.dumps(
            {
                "report_date": "2026-07-02",
                "report_type": "after_close",
                "sources": [
                    {
                        "module": "market_indices",
                        "source_name": "Bad Fixture",
                        "source_url": "fixture://bad/market",
                        "source_type": "data_api",
                        "published_at": "2026-07-02T15:05:00+08:00",
                        "content_type": "application/json",
                        "content": {"headline": "bad advice"},
                        "facts": [
                            {
                                "fact_id": "fact-bad-001",
                                "claim": "建议买入指数成分股。",
                                "classification": "fact",
                                "confidence": "high",
                                "used_in_sections": ["market_indices"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return fixture_path


def _config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
app:
  database_path: "{(tmp_path / "briefing.sqlite").as_posix()}"
  raw_dir: "{(tmp_path / "raw").as_posix()}"
  reports_dir: "{(tmp_path / "reports").as_posix()}"
generation:
  provider: template
report_types:
  after_close:
    modules:
      market_indices: true
      policy_regulation: true
      risk_points: true
  pre_open_update:
    modules:
      overnight_context: true
      today_watchpoints: true
""",
        encoding="utf-8",
    )
    return config_path


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


def test_fixture_pipeline_preserves_fact_audit_history_across_repeated_runs(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    first = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-a",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )
    second = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-b",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )

    first_facts = store.list_facts("run-a")
    second_facts = store.list_facts("run-b")
    first_fact_ids = {fact.fact_id for fact in first_facts}
    second_fact_ids = {fact.fact_id for fact in second_facts}

    assert len(first_facts) == 4
    assert len(second_facts) == 4
    assert first_fact_ids.isdisjoint(second_fact_ids)
    assert all(fact_id.startswith("fact-") for fact_id in first_fact_ids | second_fact_ids)
    assert all(fact_id.endswith(":run-a") for fact_id in first_fact_ids)
    assert all(fact_id.endswith(":run-b") for fact_id in second_fact_ids)
    assert store.get_report(first.report.report_id).all_fact_ids() == first_fact_ids
    assert store.get_report(second.report.report_id).all_fact_ids() == second_fact_ids

    for facts, fact_ids in ((first_facts, first_fact_ids), (second_facts, second_fact_ids)):
        for fact in facts:
            assert set(fact.derived_from_fact_ids) <= fact_ids

    ledger = json.loads(Path(second.report.fact_ledger_path).read_text(encoding="utf-8"))
    assert {record["fact_id"] for record in ledger} == second_fact_ids


def test_fixture_pipeline_marks_valid_run_completed(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    run_fixture_pipeline(
        PipelineRequest(
            run_id="run-completed-001",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )

    run = store.get_run("run-completed-001")

    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.completed_at is not None
    assert run.warning_count == 0


def test_fixture_pipeline_marks_validation_warnings_and_returns_errors(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    result = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-warning-001",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=_bad_fixture(tmp_path),
        ),
        config=config,
        store=store,
    )
    run = store.get_run("run-warning-001")

    assert result.validation_errors == [
        "section market_indices contains banned phrase 建议买入"
    ]
    assert run is not None
    assert run.status == RunStatus.COMPLETED_WITH_WARNINGS
    assert run.completed_at is not None
    assert run.warning_count == 1


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


def test_main_prints_markdown_path_on_success(tmp_path, monkeypatch, capsys):
    config_path = _config_file(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market-briefing",
            "--config",
            str(config_path),
            "--run-id",
            "cli-success-001",
            "--report-date",
            "2026-07-02",
            "--report-type",
            "after_close",
            "--fixture-path",
            "tests/fixtures/after_close_sources.json",
        ],
    )

    main()
    captured = capsys.readouterr()

    assert captured.out == (
        f"{tmp_path / 'reports' / '2026-07-02' / 'after_close' / 'cli-success-001' / 'briefing.md'}\n"
    )
    assert captured.err == ""


def test_main_prints_validation_errors_to_stderr_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    config_path = _config_file(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market-briefing",
            "--config",
            str(config_path),
            "--run-id",
            "cli-warning-001",
            "--report-date",
            "2026-07-02",
            "--report-type",
            "after_close",
            "--fixture-path",
            str(_bad_fixture(tmp_path)),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert captured.out == ""
    assert "section market_indices contains banned phrase 建议买入" in captured.err
