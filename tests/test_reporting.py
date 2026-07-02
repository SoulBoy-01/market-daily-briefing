from datetime import datetime, timezone

from market_briefing.domain import AtomicFact, FactClassification, ReportType, SourceType
from market_briefing.reporting import build_report, render_html, render_markdown


def _fact(
    fact_id: str,
    module: str,
    claim: str,
    classification: FactClassification = FactClassification.FACT,
    used_in_sections: list[str] | None = None,
) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
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
        derived_from_fact_ids=["fact-001"]
        if classification == FactClassification.INFERENCE
        else [],
        used_in_sections=[module] if used_in_sections is None else used_in_sections,
    )


def test_build_report_groups_facts_by_section_and_marks_inferences():
    facts = [
        _fact("fact-001", "market_indices", "上证指数收涨。"),
        _fact("fact-002", "risk_points", "风险偏好仍需观察。", FactClassification.INFERENCE),
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
    assert [section.section_id for section in report.sections] == ["market_indices", "risk_points"]
    assert "推测/归纳" in report.sections[1].body
    assert report.all_fact_ids() == {"fact-001", "fact-002"}


def test_build_report_renders_all_fact_classification_labels():
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


def test_build_report_falls_back_to_module_when_used_in_sections_is_empty():
    facts = [_fact("fact-001", "market_indices", "上证指数收涨。", used_in_sections=[])]

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

    assert [section.section_id for section in report.sections] == ["market_indices"]
    assert report.sections[0].fact_ids == ("fact-001",)


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
    facts = [_fact("fact-001", "market_indices", "上证指数收涨。")]
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
    assert "上证指数收涨" in html
