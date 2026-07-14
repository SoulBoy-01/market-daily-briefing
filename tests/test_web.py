from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from market_briefing.app import create_app, default_config_path
from market_briefing.config import AppConfig
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FactLine,
    ModuleCoverage,
    ModuleCoverageStatus,
    Report,
    ReportSection,
    ReportType,
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


def test_report_and_dashboard_show_coverage_and_safe_warning_summaries(tmp_path):
    store, client = _store_and_client(tmp_path)
    run_response = _run_fixture(client)
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    store.save_run_warnings(
        [
            RunWarning(
                warning_id="warning-web-policy",
                run_id="web-after-close-001",
                source_name="示例交易所",
                module="policy_regulation",
                message="详情页检查失败",
                detail="Traceback: secret parser diagnostics",
                created_at=created_at,
            )
        ]
    )
    store.save_module_coverage(
        [
            ModuleCoverage(
                coverage_id="coverage-web-market",
                run_id="web-after-close-001",
                module="market_indices",
                status=ModuleCoverageStatus.COVERED,
                source_name="样例市场数据",
                message="指数样例已覆盖。",
                recorded_at=created_at,
            ),
            ModuleCoverage(
                coverage_id="coverage-web-policy",
                run_id="web-after-close-001",
                module="policy_regulation",
                status=ModuleCoverageStatus.FAILED,
                source_name="示例交易所",
                message="官方详情页未完成覆盖。",
                recorded_at=created_at,
            ),
        ]
    )

    report_response = client.get(run_response.headers["location"])
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


def test_dashboard_rejects_duplicate_run_with_chinese_conflict(tmp_path):
    client = _client(tmp_path, raise_server_exceptions=False)

    first_response = _run_fixture(client)
    duplicate_response = _run_fixture(client)

    assert first_response.status_code == 303
    assert duplicate_response.status_code == 409
    assert "运行 ID 已存在，请使用新的运行 ID" in duplicate_response.text


def test_dashboard_shows_after_close_sections_as_review_material(tmp_path):
    store, client = _store_and_client(tmp_path)
    store.save_report(
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
        )
    )
    store.save_report(
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
        )
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
    run_response = _run_fixture(client)
    note = "这段备注应当被保留。"
    created_at = datetime(2026, 7, 2, 8, 30, tzinfo=timezone.utc)
    store.save_run_warnings(
        [
            RunWarning(
                warning_id="warning-feedback-rerender",
                run_id="web-after-close-001",
                source_name="示例交易所",
                module="policy_regulation",
                message="反馈回填时也应保留",
                detail="Traceback: hidden detail",
                created_at=created_at,
            )
        ]
    )
    store.save_module_coverage(
        [
            ModuleCoverage(
                coverage_id="coverage-feedback-rerender",
                run_id="web-after-close-001",
                module="policy_regulation",
                status=ModuleCoverageStatus.FAILED,
                source_name="示例交易所",
                message="反馈回填时覆盖状态也应保留。",
                recorded_at=created_at,
            )
        ]
    )

    feedback_response = client.post(
        run_response.headers["location"] + "/feedback",
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
    assert store.list_feedback("report-web-after-close-001") == []


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
    store.save_facts([fact])
    store.save_report(report)

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
    store.save_report(report)

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
    store.save_facts([fact])
    store.save_report(report)
    client = TestClient(create_app(config=config, store=store))

    response = client.get("/reports/report-unsafe-url")

    assert response.status_code == 200
    assert "javascript:alert(1)" in response.text
    assert 'href="javascript:alert(1)"' not in response.text
