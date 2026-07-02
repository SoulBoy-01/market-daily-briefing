from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from market_briefing.app import create_app, default_config_path
from market_briefing.config import AppConfig
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    Report,
    ReportSection,
    ReportType,
    SourceType,
)
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


def _store_and_client(tmp_path, *, raise_server_exceptions=True):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    client = TestClient(
        create_app(config=config, store=store),
        raise_server_exceptions=raise_server_exceptions,
    )
    return store, client


def _client(tmp_path, *, raise_server_exceptions=True):
    return _store_and_client(
        tmp_path,
        raise_server_exceptions=raise_server_exceptions,
    )[1]


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


def test_default_config_path_does_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config_path = default_config_path()

    assert config_path.is_file()
    assert config_path.name == "default.yaml"


def test_dashboard_can_trigger_fixture_run_and_show_report(tmp_path):
    client = _client(tmp_path)

    run_response = _run_fixture(client)

    assert run_response.status_code == 303
    report_response = client.get(run_response.headers["location"])
    assert report_response.status_code == 200
    assert "2026-07-02" in report_response.text
    assert "fact-market-001" in report_response.text


def test_dashboard_rejects_unsafe_fixture_run_inputs(tmp_path):
    client = _client(tmp_path, raise_server_exceptions=False)
    unsafe_requests = [
        {
            "run_id": "bad/run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        {
            "run_id": "bad\\run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        {
            "run_id": "bad..run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        {
            "run_id": "safe-run",
            "report_date": "2026/07/02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        {
            "run_id": "safe-run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "../after_close_sources.json",
        },
        {
            "run_id": "safe-run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": str(Path("tests/fixtures/after_close_sources.json").resolve()),
        },
    ]

    for payload in unsafe_requests:
        response = client.post("/runs/fixture", data=payload, follow_redirects=False)

        assert response.status_code == 400


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


def test_dashboard_rejects_feedback_for_unknown_section(tmp_path):
    store, client = _store_and_client(tmp_path)
    run_response = _run_fixture(client)

    feedback_response = client.post(
        run_response.headers["location"] + "/feedback",
        data={
            "section_id": "not-a-section",
            "score": "4",
            "tags": ["insufficient_risk"],
            "note": "This should not be saved.",
        },
        follow_redirects=False,
    )

    assert feedback_response.status_code == 400
    assert store.list_feedback("report-web-after-close-001") == []


def test_report_blocks_unsafe_source_url_links(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    fact = AtomicFact(
        fact_id="fact-unsafe-url-001",
        run_id="run-unsafe-url",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="Unsafe source URL should render as text.",
        classification=FactClassification.FACT,
        source_name="Unsafe Source",
        source_url="javascript:alert(1)",
        source_type=SourceType.OTHER,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="low",
        raw_snapshot_path="raw/unsafe.json",
        used_in_sections=["market_indices"],
    )
    report = Report(
        report_id="report-unsafe-url",
        run_id="run-unsafe-url",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Unsafe URL report",
        sections=[
            ReportSection(
                section_id="market_indices",
                title="Market indices",
                body="Unsafe source URL should render as text. [fact-unsafe-url-001]",
                fact_ids=["fact-unsafe-url-001"],
                status="ok",
            )
        ],
        markdown_path="reports/unsafe.md",
        html_path="reports/unsafe.html",
        fact_ledger_path="reports/unsafe.json",
    )
    store.save_facts([fact])
    store.save_report(report)
    client = TestClient(create_app(config=config, store=store))

    response = client.get("/reports/report-unsafe-url")

    assert response.status_code == 200
    assert "javascript:alert(1)" in response.text
    assert 'href="javascript:alert(1)"' not in response.text
