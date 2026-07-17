from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from market_briefing.app import create_app, default_config_path
from market_briefing.audit import write_snapshot_text
from market_briefing.config import AppConfig
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


def _publish_report(
    store,
    tmp_path,
    report,
    *,
    facts=(),
    warnings=(),
    module_coverage=(),
):
    report_dir = tmp_path / "published" / report.report_id
    report_dir.mkdir(parents=True)
    markdown_path = report_dir / "briefing.md"
    html_path = report_dir / "briefing.html"
    fact_ledger_path = report_dir / "fact_ledger.json"
    for path in (markdown_path, html_path, fact_ledger_path):
        path.write_text("published test artifact", encoding="utf-8")
    published_report = replace(
        report,
        markdown_path=str(markdown_path),
        html_path=str(html_path),
        fact_ledger_path=str(fact_ledger_path),
    )
    snapshots = []
    published_facts = []
    for index, fact in enumerate(facts):
        snapshot_file = write_snapshot_text(
            report_dir / f"snapshot-{index}.json",
            "{}",
        )
        snapshot_id = f"snapshot-{fact.fact_id}"
        snapshots.append(
            RawSnapshot(
                snapshot_id=snapshot_id,
                run_id=report.run_id,
                module=fact.module,
                source_name=fact.source_name,
                source_url=fact.source_url,
                source_type=fact.source_type,
                fetched_at=fact.fetched_at,
                content_type="application/json",
                raw_path=str(snapshot_file.path),
                content_sha256=snapshot_file.content_sha256,
                provider_name=fact.source_name,
            )
        )
        published_facts.append(
            replace(
                fact,
                raw_snapshot_path=str(snapshot_file.path),
                source_snapshot_id=snapshot_id,
            )
        )
    run = Run.create(
        run_id=report.run_id,
        report_date=report.report_date,
        report_type=report.report_type,
        enabled_modules=sorted({fact.module for fact in facts}),
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    store.publish_run_bundle(
        snapshots=snapshots,
        facts=published_facts,
        report=published_report,
        target_status=(
            RunStatus.COMPLETED_WITH_WARNINGS if warnings else RunStatus.COMPLETED
        ),
        warnings=list(warnings),
        module_coverage=list(module_coverage),
    )
    return published_report


def test_dashboard_renders_loop_first_sections(tmp_path):
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert '<html lang="zh-CN">' in response.text
    assert "每日市场简报工作台" in response.text
    assert "不构成任何投资建议" in response.text
    assert "事实账本" in response.text
    assert "分节反馈" in response.text


def test_dashboard_renders_tour_for_empty_workspace(tmp_path):
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="run-fixture-form"' in response.text
    assert 'id="onboarding-tour"' in response.text
    assert "新手阅读引导" in response.text
    assert 'data-tour-target="run-fixture-form"' in response.text
    assert "先运行一次样例数据" in response.text


def test_run_forms_default_to_china_market_today(tmp_path):
    client = _client(tmp_path)
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    dashboard_response = client.get("/")
    run_form_response = client.get("/runs/fixture")

    assert dashboard_response.status_code == 200
    assert run_form_response.status_code == 200
    assert f'name="report_date" type="date" value="{today}"' in dashboard_response.text
    assert f'name="report_date" type="date" value="{today}"' in run_form_response.text


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
    assert "返回工作台" in report_response.text
    assert "不构成任何投资建议" in report_response.text
    assert "事实账本" in report_response.text
    assert "事实分类" in report_response.text
    assert "原始快照" in report_response.text
    assert "保存反馈" in report_response.text
    assert "2026-07-02" in report_response.text
    assert "fact-market-001" in report_response.text


def test_report_and_dashboard_show_publication_and_audit_metadata(tmp_path):
    store, client = _store_and_client(tmp_path)
    run_response = _run_fixture(client)
    report_response = client.get(run_response.headers["location"])
    dashboard_response = client.get("/")
    snapshot = store.list_snapshots("web-after-close-001")[0]

    for response in (report_response, dashboard_response):
        assert response.status_code == 200
        assert "运行状态" in response.text
        assert "已完成" in response.text
        assert "发布状态" in response.text
        assert "正式发布" in response.text

    assert "运行事件" in report_response.text
    assert "已创建" in report_response.text
    assert "运行中" in report_response.text
    assert "SHA-256" in report_response.text
    assert snapshot.content_sha256 in report_response.text
    assert snapshot.provider_name in report_response.text
    assert snapshot.license_ref in report_response.text


def test_report_shows_candidate_review_audit_chain(tmp_path):
    store, client = _store_and_client(tmp_path)
    fetched_at = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    run = Run.create(
        run_id="web-candidate-audit",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    report_dir = tmp_path / "candidate-audit"
    report_dir.mkdir()
    snapshot_file = write_snapshot_text(report_dir / "official.html", "official fixture")
    snapshot = RawSnapshot(
        snapshot_id="snapshot-web-candidate-audit",
        run_id=run.run_id,
        module="policy_regulation",
        source_name="示例交易所",
        source_url="fixture://candidate-audit",
        source_type=SourceType.EXCHANGE,
        fetched_at=fetched_at,
        content_type="text/html",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="示例交易所",
        license_ref="fixture:candidate-audit",
    )
    candidate = EvidenceCandidate(
        candidate_id="candidate-web-audit",
        run_id=run.run_id,
        snapshot_id=snapshot.snapshot_id,
        module=snapshot.module,
        title="交易所发布规则说明",
        detail_url="fixture://candidate-audit",
        published_at=fetched_at,
        excerpt="交易所发布规则说明。",
        suggested_classification=FactClassification.FACT,
        created_at=fetched_at,
    )
    store.save_candidate(candidate)
    store.review_candidate(
        candidate.candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="local-maintainer",
        note="已核对本地详情页。",
        approved_fact_id="fact-web-candidate-audit",
        reviewed_at=fetched_at,
    )
    fact = AtomicFact(
        fact_id="fact-web-candidate-audit",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        module=snapshot.module,
        claim=candidate.excerpt,
        classification=FactClassification.FACT,
        source_name=snapshot.source_name,
        source_url=candidate.detail_url,
        source_type=snapshot.source_type,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=snapshot.raw_path,
        source_candidate_id=candidate.candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
    )
    paths = [
        report_dir / "briefing.md",
        report_dir / "briefing.html",
        report_dir / "fact_ledger.json",
    ]
    for path in paths:
        path.write_text("candidate audit artifact", encoding="utf-8")
    report = Report(
        report_id="report-web-candidate-audit",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="候选审核链报告",
        sections=[],
        markdown_path=str(paths[0]),
        html_path=str(paths[1]),
        fact_ledger_path=str(paths[2]),
    )
    store.publish_run_bundle(
        snapshots=[snapshot],
        facts=[fact],
        report=report,
        target_status=RunStatus.COMPLETED,
    )

    response = client.get(f"/reports/{report.report_id}")

    assert response.status_code == 200
    assert "候选审核链" in response.text
    assert candidate.candidate_id in response.text
    assert snapshot.snapshot_id in response.text
    assert "待审核" in response.text
    assert "已批准" in response.text
    assert "local-maintainer" in response.text
    assert "已核对本地详情页。" in response.text
    assert fact.fact_id in response.text


def test_report_and_dashboard_show_coverage_and_safe_warning_summaries(tmp_path):
    store, client = _store_and_client(tmp_path)
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    report = Report(
        report_id="report-web-observability",
        run_id="web-observability",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="A股盘后简报 2026-07-02",
        sections=[],
        markdown_path="unused.md",
        html_path="unused.html",
        fact_ledger_path="unused.json",
    )
    warning = RunWarning(
        warning_id="warning-web-policy",
        run_id=report.run_id,
        source_name="示例交易所",
        module="policy_regulation",
        message="详情页检查失败",
        detail="Traceback: secret parser diagnostics",
        created_at=created_at,
    )
    coverage = [
            ModuleCoverage(
                coverage_id="coverage-web-market",
                run_id=report.run_id,
                module="market_indices",
                status=ModuleCoverageStatus.COVERED,
                source_name="样例市场数据",
                message="指数样例已覆盖。",
                recorded_at=created_at,
            ),
            ModuleCoverage(
                coverage_id="coverage-web-policy",
                run_id=report.run_id,
                module="policy_regulation",
                status=ModuleCoverageStatus.FAILED,
                source_name="示例交易所",
                message="官方详情页未完成覆盖。",
                recorded_at=created_at,
            )
    ]
    published_report = _publish_report(
        store,
        tmp_path,
        report,
        warnings=[warning],
        module_coverage=coverage,
    )

    report_response = client.get(f"/reports/{published_report.report_id}")
    dashboard_response = client.get("/")

    for response in (report_response, dashboard_response):
        assert response.status_code == 200
        assert "模块覆盖" in response.text
        assert "市场指数" in response.text
        assert "已覆盖" in response.text
        assert "政策/监管" in response.text
        assert "检查失败" in response.text
        assert "示例交易所 / 政策/监管 / 详情页检查失败" in response.text
        assert "Traceback" not in response.text
        assert "secret parser diagnostics" not in response.text


def test_report_blocks_display_when_published_snapshot_is_tampered(tmp_path):
    store, client = _store_and_client(tmp_path, raise_server_exceptions=False)
    run_response = _run_fixture(client)
    report_id = run_response.headers["location"].removeprefix("/reports/")
    snapshot = store.list_snapshots("web-after-close-001")[0]
    Path(snapshot.raw_path).write_text("tampered", encoding="utf-8")

    response = client.get(f"/reports/{report_id}")

    assert response.status_code == 409
    assert "审计完整性校验失败" in response.text


def test_dashboard_blocks_preview_when_published_snapshot_is_tampered(tmp_path):
    store, client = _store_and_client(tmp_path, raise_server_exceptions=False)
    _run_fixture(client)
    snapshot = store.list_snapshots("web-after-close-001")[0]
    Path(snapshot.raw_path).write_text("tampered", encoding="utf-8")

    response = client.get("/")

    assert response.status_code == 409
    assert "审计完整性校验失败" in response.text


def test_dashboard_blocks_when_non_preview_history_report_is_tampered(tmp_path):
    store, client = _store_and_client(tmp_path, raise_server_exceptions=False)
    fetched_at = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)

    after_close_fact = AtomicFact(
        fact_id="fact-history-after-close",
        run_id="run-history-after-close",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="Published after-close fact.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://history/after-close",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path="unused",
    )
    after_close_report = Report(
        report_id="report-history-after-close",
        run_id=after_close_fact.run_id,
        report_date=after_close_fact.report_date,
        report_type=after_close_fact.report_type,
        title="After-close history report",
        sections=[],
        markdown_path="unused",
        html_path="unused",
        fact_ledger_path="unused",
    )
    _publish_report(store, tmp_path, after_close_report, facts=[after_close_fact])

    pre_open_fact = replace(
        after_close_fact,
        fact_id="fact-history-pre-open",
        run_id="run-history-pre-open",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        module="overnight_context",
        claim="Published pre-open fact.",
        source_url="fixture://history/pre-open",
    )
    pre_open_report = replace(
        after_close_report,
        report_id="report-history-pre-open",
        run_id=pre_open_fact.run_id,
        report_date=pre_open_fact.report_date,
        report_type=pre_open_fact.report_type,
        title="Pre-open history report",
    )
    _publish_report(store, tmp_path, pre_open_report, facts=[pre_open_fact])
    damaged_snapshot = store.list_snapshots(pre_open_report.run_id)[0]
    Path(damaged_snapshot.raw_path).write_text("tampered", encoding="utf-8")

    response = client.get("/")

    assert response.status_code == 409
    assert "审计完整性校验失败" in response.text


def test_feedback_blocks_when_published_snapshot_is_tampered(tmp_path):
    store, client = _store_and_client(tmp_path, raise_server_exceptions=False)
    run_response = _run_fixture(client)
    snapshot = store.list_snapshots("web-after-close-001")[0]
    Path(snapshot.raw_path).write_text("tampered", encoding="utf-8")

    response = client.post(
        run_response.headers["location"] + "/feedback",
        data={
            "section_id": "one_sentence_conclusion",
            "score": "6",
            "note": "不应绕过审计损坏阻断。",
        },
    )

    assert response.status_code == 409
    assert "审计完整性校验失败" in response.text
    assert store.list_feedback("report-web-after-close-001") == []


def test_dashboard_rejects_duplicate_run_with_chinese_conflict(tmp_path):
    client = _client(tmp_path, raise_server_exceptions=False)

    first_response = _run_fixture(client)
    duplicate_response = _run_fixture(client)

    assert first_response.status_code == 303
    assert duplicate_response.status_code == 409
    assert "运行 ID 已存在，请使用新的运行 ID" in duplicate_response.text


def test_web_hides_report_that_did_not_complete_publication_transaction(tmp_path):
    store, client = _store_and_client(tmp_path, raise_server_exceptions=False)
    run = Run.create(
        run_id="web-running-report",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)
    report = Report(
        report_id="report-web-running",
        run_id=run.run_id,
        report_date=run.report_date,
        report_type=run.report_type,
        title="不应可见的报告",
        sections=[],
        markdown_path=str(tmp_path / "running.md"),
        html_path=str(tmp_path / "running.html"),
        fact_ledger_path=str(tmp_path / "running.json"),
    )
    store.save_report(report)

    dashboard_response = client.get("/")
    detail_response = client.get(f"/reports/{report.report_id}")
    feedback_response = client.post(
        f"/reports/{report.report_id}/feedback",
        data={"section_id": "none", "score": "4"},
    )

    assert dashboard_response.status_code == 200
    assert report.title not in dashboard_response.text
    assert detail_response.status_code == 404
    assert feedback_response.status_code == 404


def test_dashboard_shows_after_close_sections_as_review_material(tmp_path):
    store, client = _store_and_client(tmp_path)
    _publish_report(
        store,
        tmp_path,
        Report(
            report_id="report-thin-pre-open",
            run_id="thin-pre-open",
            report_date="2026-07-03",
            report_type=ReportType.PRE_OPEN_UPDATE,
            title="A股盘前更新 2026-07-03",
            sections=[
                ReportSection(
                    section_id="today_watchpoints",
                    title="今日关注点",
                    body="盘前更新正文。",
                    fact_ids=[],
                    status="ok",
                )
            ],
            markdown_path="reports/pre.md",
            html_path="reports/pre.html",
            fact_ledger_path="reports/pre.json",
        ),
    )
    _publish_report(
        store,
        tmp_path,
        Report(
            report_id="report-review-after-close",
            run_id="review-after-close",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            title="A股盘后简报 2026-07-02",
            sections=[
                ReportSection(
                    section_id="risk_points",
                    title="风险提示",
                    body="这是给用户审阅的盘后风险提示正文。",
                    fact_ids=[],
                    status="ok",
                )
            ],
            markdown_path="reports/after.md",
            html_path="reports/after.html",
            fact_ledger_path="reports/after.json",
        ),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "审阅样稿" in response.text
    assert "新手阅读引导" in response.text
    assert "1/5" in response.text
    assert "下一步" in response.text
    assert "跳过引导" in response.text
    assert "重新查看引导" in response.text
    assert 'id="onboarding-tour"' in response.text
    assert 'data-tour-target="review-one_sentence_conclusion"' in response.text
    assert response.text.index("</main>") < response.text.index('id="onboarding-tour"')
    assert "styles.css?v=" in response.text
    assert "tour.js?v=" in response.text
    assert "guide-panel" not in response.text
    assert "A股盘后简报 2026-07-02" in response.text
    assert "这是给用户审阅的盘后风险提示正文。" in response.text


def test_onboarding_tour_scrolls_to_section_and_positions_card_near_target():
    tour_script = Path("src/market_briefing/static/tour.js").read_text(encoding="utf-8")
    tour_styles = Path("src/market_briefing/static/styles.css").read_text(encoding="utf-8")

    assert "scrollIntoView" in tour_script
    assert "positionTourCard" in tour_script
    assert "activeTarget" in tour_script
    assert ".tour-card {" in tour_styles
    assert "position: fixed;" in tour_styles


def test_onboarding_tour_returns_to_top_after_completion_only():
    tour_script = Path("src/market_briefing/static/tour.js").read_text(encoding="utf-8")

    assert "function completeTour()" in tour_script
    assert "window.scrollTo({ top: 0, behavior: \"smooth\" })" in tour_script
    assert "skipButton.addEventListener(\"click\", closeTour)" in tour_script


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
        {
            "run_id": "safe-run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "\\Windows\\win.ini",
        },
        {
            "run_id": "safe-run",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "C:foo",
        },
    ]

    for payload in unsafe_requests:
        response = client.post("/runs/fixture", data=payload, follow_redirects=False)

        assert response.status_code == 400


def test_default_app_normalizes_default_paths_under_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_root = default_config_path().parent.parent

    default_app = create_app()
    config = default_app.state.config

    for path in (config.database_path, config.raw_dir, config.reports_dir):
        assert path.is_absolute()
        assert path.is_relative_to(project_root)


def test_dashboard_can_submit_feedback(tmp_path):
    client = _client(tmp_path)
    run_response = _run_fixture(client)
    note = "Risk detail needs clearer source linkage."

    feedback_response = client.post(
        run_response.headers["location"] + "/feedback",
        data={
            "section_id": "one_sentence_conclusion",
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
    assert "<strong>今日一句话结论</strong>" in report_response.text
    assert "<strong>one_sentence_conclusion</strong>" not in report_response.text


def test_report_feedback_score_explains_rating_direction(tmp_path):
    client = _client(tmp_path)
    run_response = _run_fixture(client)

    report_response = client.get(run_response.headers["location"])

    assert report_response.status_code == 200
    assert "1=最差 · 5=最好" in report_response.text


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


def test_report_feedback_validation_errors_rerender_with_chinese_messages_and_values(tmp_path):
    store, client = _store_and_client(tmp_path)
    note = "这段备注应当被保留。"
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    report = Report(
        report_id="report-feedback-rerender",
        run_id="run-feedback-rerender",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="A股盘后简报 2026-07-02",
        sections=[
            ReportSection(
                section_id="next_watchlist",
                title="下一轮观察清单",
                body="- 待验证：后续观察事项。",
                fact_ids=[],
                status="ok",
            )
        ],
        markdown_path="unused.md",
        html_path="unused.html",
        fact_ledger_path="unused.json",
    )
    warning = RunWarning(
        warning_id="warning-feedback-rerender",
        run_id=report.run_id,
        source_name="示例交易所",
        module="policy_regulation",
        message="反馈回填时也应保留",
        detail="Traceback: hidden detail",
        created_at=created_at,
    )
    coverage = [
            ModuleCoverage(
                coverage_id="coverage-feedback-rerender",
                run_id=report.run_id,
                module="policy_regulation",
                status=ModuleCoverageStatus.FAILED,
                source_name="示例交易所",
                message="反馈回填时覆盖状态也应保留。",
                recorded_at=created_at,
            )
    ]
    published_report = _publish_report(
        store,
        tmp_path,
        report,
        warnings=[warning],
        module_coverage=coverage,
    )

    feedback_response = client.post(
        f"/reports/{published_report.report_id}/feedback",
        data={
            "section_id": "next_watchlist",
            "score": "6",
            "tags": ["insufficient_risk", "unexpected_tag"],
            "note": note,
        },
        follow_redirects=False,
    )

    assert feedback_response.status_code == 400
    assert "评分必须在 1 到 5 之间" in feedback_response.text
    assert "反馈标签无效：unexpected_tag" in feedback_response.text
    assert note in feedback_response.text
    assert 'value="6"' in feedback_response.text
    assert 'value="insufficient_risk" checked' in feedback_response.text
    assert "示例交易所 / 政策/监管 / 反馈回填时也应保留" in feedback_response.text
    assert "检查失败" in feedback_response.text
    assert "Traceback" not in feedback_response.text
    assert store.list_feedback(published_report.report_id) == []


def test_report_feedback_note_too_long_rerenders_with_original_note(tmp_path):
    store, client = _store_and_client(tmp_path)
    run_response = _run_fixture(client)
    note = "太长" * 121

    feedback_response = client.post(
        run_response.headers["location"] + "/feedback",
        data={
            "section_id": "next_watchlist",
            "score": "4",
            "tags": ["unclear_citation"],
            "note": note,
        },
        follow_redirects=False,
    )

    assert feedback_response.status_code == 400
    assert "备注不能超过 240 个字" in feedback_response.text
    assert note in feedback_response.text
    assert 'value="unclear_citation" checked' in feedback_response.text
    assert store.list_feedback("report-web-after-close-001") == []


def test_report_and_dashboard_render_structured_fact_lines(tmp_path):
    store, client = _store_and_client(tmp_path)
    fetched_at = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    fact = AtomicFact(
        fact_id="fact-structured-001",
        run_id="run-structured",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="Shanghai Composite closed higher.",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://structured",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path="raw/structured.json",
        used_in_sections=["market_indices"],
    )
    report = Report(
        report_id="report-structured",
        run_id="run-structured",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="Structured report",
        sections=[
            ReportSection(
                section_id="one_sentence_conclusion",
                title="今日一句话结论",
                body="- **事实** Shanghai Composite closed higher. [fact-structured-001]",
                fact_ids=["fact-structured-001"],
                status="ok",
                fact_lines=[
                    FactLine(
                        fact_id="fact-structured-001",
                        classification=FactClassification.FACT,
                        claim="Shanghai Composite closed higher.",
                    )
                ],
            ),
            ReportSection(
                section_id="next_watchlist",
                title="下一轮观察清单",
                body="- 待验证：Shanghai Composite closed higher. [fact-structured-001]",
                fact_ids=["fact-structured-001"],
                status="ok",
                fact_lines=[
                    FactLine(
                        fact_id="fact-structured-001",
                        classification=FactClassification.FACT,
                        claim="Shanghai Composite closed higher.",
                    )
                ],
            ),
        ],
        markdown_path="reports/structured.md",
        html_path="reports/structured.html",
        fact_ledger_path="reports/structured.json",
    )
    _publish_report(store, tmp_path, report, facts=[fact])

    report_response = client.get("/reports/report-structured")
    dashboard_response = client.get("/")

    assert report_response.status_code == 200
    assert dashboard_response.status_code == 200
    for html in (report_response.text, dashboard_response.text):
        assert 'class="section-body structured"' in html
        assert 'class="fact-line fact-line-fact"' in html
        assert 'class="cls-badge cls-fact"' in html
        assert "Shanghai Composite closed higher." in html
        assert "待验证：" in html
        assert "**事实**" not in html


def test_report_omits_fact_chip_row_when_section_has_no_fact_ids(tmp_path):
    store, client = _store_and_client(tmp_path)
    report = Report(
        report_id="report-empty-fact-chips",
        run_id="run-empty-fact-chips",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        title="A股早盘补充 2026-07-03",
        sections=[
            ReportSection(
                section_id="previous_feedback",
                title="上一轮反馈回执",
                body="- 暂无历史反馈。",
                fact_ids=[],
                status="ok",
            )
        ],
        markdown_path="reports/empty.md",
        html_path="reports/empty.html",
        fact_ledger_path="reports/empty.json",
    )
    _publish_report(store, tmp_path, report)

    response = client.get("/reports/report-empty-fact-chips")

    assert response.status_code == 200
    assert "上一轮反馈回执" in response.text
    assert 'class="fact-chip-row"' not in response.text


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
    _publish_report(store, tmp_path, report, facts=[fact])
    client = TestClient(create_app(config=config, store=store))

    response = client.get("/reports/report-unsafe-url")

    assert response.status_code == 200
    assert "javascript:alert(1)" in response.text
    assert 'href="javascript:alert(1)"' not in response.text
