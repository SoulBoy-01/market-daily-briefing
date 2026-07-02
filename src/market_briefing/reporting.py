from __future__ import annotations

from collections import defaultdict

from markdown_it import MarkdownIt

from market_briefing.domain import AtomicFact, FactClassification, Report, ReportSection, ReportType


SECTION_TITLES = {
    "market_indices": "指数表现",
    "market_temperature": "市场温度",
    "sector_moves": "板块表现",
    "policy_regulation": "政策与监管",
    "major_news": "重大新闻",
    "risk_points": "风险提示",
    "overnight_context": "隔夜环境",
    "policy_news_delta": "政策新闻变化",
    "today_watchpoints": "今日关注点",
}

REPORT_TITLES = {
    ReportType.AFTER_CLOSE: "A股盘后简报",
    ReportType.PRE_OPEN_UPDATE: "A股早盘补充",
}

CLASSIFICATION_LABELS = {
    FactClassification.FACT: "事实",
    FactClassification.OPINION: "观点",
    FactClassification.INFERENCE: "推测/归纳",
    FactClassification.UNVERIFIED: "待确认",
}


def build_report(
    report_id: str,
    run_id: str,
    report_date: str,
    report_type: ReportType,
    facts: list[AtomicFact],
    markdown_path: str,
    html_path: str,
    fact_ledger_path: str,
) -> Report:
    grouped: dict[str, list[AtomicFact]] = defaultdict(list)
    for fact in facts:
        for section_id in fact.used_in_sections or (fact.module,):
            grouped[section_id].append(fact)

    sections = [
        ReportSection(
            section_id=section_id,
            title=SECTION_TITLES.get(section_id, section_id),
            body="\n".join(_format_fact_line(fact) for fact in section_facts),
            fact_ids=[fact.fact_id for fact in section_facts],
            status="ok",
        )
        for section_id, section_facts in grouped.items()
    ]

    return Report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        title=f"{REPORT_TITLES[report_type]} {report_date}",
        sections=sections,
        markdown_path=markdown_path,
        html_path=html_path,
        fact_ledger_path=fact_ledger_path,
    )


def render_markdown(report: Report, facts: list[AtomicFact]) -> str:
    section_blocks = [f"## {section.title}\n\n{section.body}" for section in report.sections]
    source_lines = [_format_source_line(index, fact) for index, fact in enumerate(facts, start=1)]

    return (
        "\n\n".join(
            [
                f"# {report.title}",
                *section_blocks,
                "## 来源索引",
                "\n".join(source_lines),
            ]
        )
        + "\n"
    )


def render_html(markdown: str) -> str:
    body = MarkdownIt("commonmark").render(markdown)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>Market Briefing</title></head><body>"
        f"{body}</body></html>"
    )


def _format_fact_line(fact: AtomicFact) -> str:
    label = CLASSIFICATION_LABELS[fact.classification]
    return f"- **{label}** {fact.claim} [{fact.fact_id}]"


def _format_source_line(index: int, fact: AtomicFact) -> str:
    published_at = fact.published_at.isoformat() if fact.published_at else "unknown"
    return (
        f"- [{index}] [{fact.fact_id}] {fact.source_name} ({fact.source_type.value}): "
        f"{fact.source_url}; published={published_at}"
    )
