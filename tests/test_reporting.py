from datetime import datetime, timezone

from market_briefing.domain import AtomicFact, FactClassification, ReportType, SourceType
from market_briefing.reporting import build_report, render_html, render_markdown


def _fact(
    fact_id: str,
    module: str,
    claim: str,
    classification: FactClassification = FactClassification.FACT,
    used_in_sections: list[str] | None = None,
    report_type: ReportType = ReportType.AFTER_CLOSE,
    derived_from_fact_ids: list[str] | None = None,
) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=report_type,
        module=module,
        claim=claim,
        classification=classification,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        derived_from_fact_ids=(
            derived_from_fact_ids
            if derived_from_fact_ids is not None
            else ["fact-001"]
            if classification == FactClassification.INFERENCE
            else []
        ),
        used_in_sections=[module] if used_in_sections is None else used_in_sections,
    )


def test_build_after_close_report_uses_beginner_review_structure():
    facts = [
        _fact("fact-001", "market_indices", "上证指数上涨0.52%。"),
        _fact("fact-002", "sector_moves", "机器人板块涨幅居前。"),
        _fact("fact-003", "major_news", "券商认为风险偏好有所修复。", FactClassification.OPINION),
        _fact("fact-004", "risk_points", "风险偏好仍需观察。", FactClassification.INFERENCE),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert report.title == "A股盘后简报 2026-07-02"
    assert [section.section_id for section in report.sections] == [
        "one_sentence_conclusion",
        "market_overview",
        "sector_strength",
        "fact_opinion_inference",
        "next_watchlist",
        "previous_feedback",
    ]
    assert [section.title for section in report.sections] == [
        "今日一句话结论",
        "市场全貌",
        "强弱板块",
        "事实 / 观点 / 推测分栏",
        "下一轮观察清单",
        "上一轮反馈回执",
    ]
    body = "\n".join(section.body for section in report.sections)
    assert "新手先看这句" not in body
    assert "先看市场全貌" not in body
    assert "再看强弱板块" not in body
    assert "下一轮重点观察" not in body
    assert "上证指数上涨0.52%" in report.sections[0].body
    assert "机器人板块涨幅居前" in report.sections[2].body
    assert "事实" in report.sections[3].body
    assert "观点" in report.sections[3].body
    assert "推测/归纳" in report.sections[3].body
    assert "待验证：风险偏好仍需观察" in report.sections[4].body
    assert "暂无历史反馈" in report.sections[5].body
    assert report.all_fact_ids() == {"fact-001", "fact-002", "fact-003", "fact-004"}


def test_one_sentence_conclusion_only_uses_market_facts():
    facts = [
        _fact("fact-opinion-001", "major_news", "券商认为风险偏好修复。", FactClassification.OPINION),
        _fact("fact-risk-001", "risk_points", "系统归纳风险偏好仍需观察。", FactClassification.INFERENCE),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    conclusion = report.sections[0]
    assert conclusion.section_id == "one_sentence_conclusion"
    assert "今日暂无可结论的硬事实。" in conclusion.body
    assert "券商认为风险偏好修复" not in conclusion.body
    assert conclusion.fact_ids == ()


def test_next_watchlist_excludes_opinion_and_unrooted_inference():
    facts = [
        _fact("fact-policy-001", "policy_regulation", "交易所发布监管通报。"),
        _fact("fact-news-001", "major_news", "券商认为风险偏好修复。", FactClassification.OPINION),
        _fact(
            "fact-risk-001",
            "risk_points",
            "系统归纳需要跟踪扩散。",
            FactClassification.INFERENCE,
            derived_from_fact_ids=[],
        ),
        _fact(
            "fact-risk-002",
            "risk_points",
            "系统归纳需要验证监管影响。",
            FactClassification.INFERENCE,
            derived_from_fact_ids=["fact-policy-001"],
        ),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    watchlist = report.sections[4]
    assert "待验证：交易所发布监管通报。" in watchlist.body
    assert "待验证：系统归纳需要验证监管影响。" in watchlist.body
    assert "券商认为风险偏好修复" not in watchlist.body
    assert "系统归纳需要跟踪扩散" not in watchlist.body
    assert watchlist.fact_ids == ("fact-risk-002", "fact-policy-001")


def test_build_after_close_report_renders_all_fact_classification_labels():
    facts = [
        _fact("fact-001", "market_indices", "事实口径。"),
        _fact("fact-002", "major_news", "观点口径。", FactClassification.OPINION),
        _fact("fact-003", "risk_points", "推测口径。", FactClassification.INFERENCE),
        _fact("fact-004", "policy_regulation", "待确认口径。", FactClassification.UNVERIFIED),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )
    body = "\n".join(section.body for section in report.sections)

    assert "**事实**" in body
    assert "**观点**" in body
    assert "**推测/归纳**" in body
    assert "**待确认**" in body


def test_build_after_close_report_carries_structured_fact_lines():
    facts = [
        _fact("fact-001", "market_indices", "Index closed higher.", FactClassification.FACT),
        _fact("fact-002", "major_news", "Broker expects sentiment recovery.", FactClassification.OPINION),
        _fact(
            "fact-003",
            "risk_points",
            "Watch whether the policy effect spreads.",
            FactClassification.INFERENCE,
            derived_from_fact_ids=["fact-001"],
        ),
        _fact("fact-004", "policy_regulation", "Unconfirmed market rumor.", FactClassification.UNVERIFIED),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    classification_section = report.sections[3]

    assert classification_section.section_id == "fact_opinion_inference"
    assert [line.fact_id for line in classification_section.fact_lines] == [
        "fact-001",
        "fact-002",
        "fact-003",
        "fact-004",
    ]
    assert [line.classification for line in classification_section.fact_lines] == [
        FactClassification.FACT,
        FactClassification.OPINION,
        FactClassification.INFERENCE,
        FactClassification.UNVERIFIED,
    ]
    assert classification_section.fact_lines[2].claim == "Watch whether the policy effect spreads."
    assert classification_section.fact_lines[2].derived_from_fact_ids == ("fact-001",)


def test_build_pre_open_report_still_groups_facts_by_section_and_marks_inferences():
    facts = [
        _fact(
            "fact-001",
            "today_watchpoints",
            "关注盘前消息。",
            report_type=ReportType.PRE_OPEN_UPDATE,
        ),
        _fact(
            "fact-002",
            "overnight_context",
            "隔夜风险偏好仍需观察。",
            FactClassification.INFERENCE,
            report_type=ReportType.PRE_OPEN_UPDATE,
        ),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert report.title == "A股早盘补充 2026-07-03"
    assert [section.section_id for section in report.sections] == [
        "today_watchpoints",
        "overnight_context",
        "previous_feedback",
    ]
    assert "推测/归纳" in report.sections[1].body
    assert "暂无历史反馈" in report.sections[2].body
    assert report.all_fact_ids() == {"fact-001", "fact-002"}


def test_build_pre_open_report_falls_back_to_module_when_used_in_sections_is_empty():
    facts = [
        _fact(
            "fact-001",
            "today_watchpoints",
            "盘前关注点。",
            used_in_sections=[],
            report_type=ReportType.PRE_OPEN_UPDATE,
        )
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert [section.section_id for section in report.sections] == [
        "today_watchpoints",
        "previous_feedback",
    ]
    assert report.sections[0].fact_ids == ("fact-001",)


def test_build_pre_open_report_carries_previous_feedback_section():
    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        facts=[],
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
        previous_feedback_summary="平均评分：4.0\n今日关注点：评分=4；备注=盘前重点要更具体。",
    )

    assert [section.section_id for section in report.sections] == ["previous_feedback"]
    assert "平均评分：4.0" in report.sections[0].body
    assert "盘前重点要更具体" in report.sections[0].body


def test_build_report_uses_pre_open_update_title():
    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        facts=[],
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert report.title == "A股早盘补充 2026-07-03"


def test_render_html_escapes_raw_html_in_fact_claims():
    facts = [_fact("fact-001", "market_indices", "<script>alert(1)</script>")]
    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    html = render_html(render_markdown(report, facts))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_markdown_and_html_include_sources_and_fact_ids():
    facts = [_fact("fact-001", "market_indices", "上证指数上涨。")]
    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    markdown = render_markdown(report, facts)
    html = render_html(markdown)

    assert "# A股盘后简报 2026-07-02" in markdown
    assert "## 来源索引" in markdown
    assert "[fact-001]" in markdown
    assert "fixture://source" in markdown
    assert "<h1" in html
    assert "上证指数上涨" in html
