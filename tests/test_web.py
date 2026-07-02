from pathlib import Path

from fastapi.testclient import TestClient

from market_briefing.app import create_app
from market_briefing.config import AppConfig
from market_briefing.domain import ReportType
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


def _client(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    return TestClient(create_app(config=config, store=store))


def _run_fixture(client):
    return client.post(
        "/runs/fixture",
        data={
            "run_id": "web-after-close-001",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": str(Path("tests/fixtures/after_close_sources.json")),
        },
        follow_redirects=False,
    )


def test_dashboard_renders_loop_first_sections(tmp_path):
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Loop Dashboard" in response.text
    assert "Fact ledger" in response.text
    assert "Section feedback" in response.text


def test_dashboard_can_trigger_fixture_run_and_show_report(tmp_path):
    client = _client(tmp_path)

    run_response = _run_fixture(client)

    assert run_response.status_code == 303
    report_response = client.get(run_response.headers["location"])
    assert report_response.status_code == 200
    assert "2026-07-02" in report_response.text
    assert "fact-market-001" in report_response.text


def test_dashboard_can_submit_feedback(tmp_path):
    client = _client(tmp_path)
    run_response = _run_fixture(client)
    note = "Risk detail needs clearer source linkage."

    feedback_response = client.post(
        run_response.headers["location"] + "/feedback",
        data={
            "section_id": "risk_points",
            "score": "4",
            "tags": ["insufficient_risk", "unclear_citation"],
            "note": note,
        },
        follow_redirects=False,
    )

    assert feedback_response.status_code == 303
    report_response = client.get(feedback_response.headers["location"])
    assert report_response.status_code == 200
    assert note in report_response.text
