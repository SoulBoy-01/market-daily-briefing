from __future__ import annotations

from collections import defaultdict

from markdown_it import MarkdownIt

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FactLine,
    Report,
    ReportSection,
    ReportType,
)
from market_briefing.labels import (
    fact_classification_label,
    report_title_label,
    section_label,
)


def build_report(
    report_id: str,
    run_id: str,
    report_date: str,
    report_type: ReportType,
    facts: list[AtomicFact],
    markdown_path: str,
    html_path: str,
    fact_ledger_path: str,
    previous_feedback_summary: str = "暂无历史反馈。",
) -> Report:
    sections = (
        _build_beginner_after_close_sections(facts, previous_feedback_summary)
        if report_type == ReportType.AFTER_CLOSE
        else _build_module_sections(facts, previous_feedback_summary)
    )

    return Report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        title=f"{report_title_label(report_type)} {report_date}",
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
    body = MarkdownIt("commonmark", {"html": False}).render(markdown)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>A股每日市场简报</title></head><body>"
        f"{body}</body></html>"
    )


def _build_module_sections(
    facts: list[AtomicFact],
    previous_feedback_summary: str,
) -> list[ReportSection]:
    grouped: dict[str, list[AtomicFact]] = defaultdict(list)
    for fact in facts:
        for section_id in fact.used_in_sections or (fact.module,):
            grouped[section_id].append(fact)

    sections = [
        ReportSection(
            section_id=section_id,
            title=section_label(section_id),
            body="\n".join(_format_fact_line(fact) for fact in section_facts),
            fact_ids=[fact.fact_id for fact in section_facts],
            status="ok",
            fact_lines=_fact_lines(section_facts),
        )
        for section_id, section_facts in grouped.items()
    ]
    sections.append(
        _section(
            "previous_feedback",
            _feedback_summary_lines(previous_feedback_summary),
            [],
        )
    )
    return sections


def _build_beginner_after_close_sections(
    facts: list[AtomicFact],
    previous_feedback_summary: str,
) -> list[ReportSection]:
    market_facts = _facts_for_modules(facts, {"market_indices", "market_temperature"})
    sector_facts = _facts_for_modules(facts, {"sector_moves"})
    policy_facts = _facts_for_modules(facts, {"policy_regulation"})
    risk_facts = _facts_for_modules(facts, {"risk_points"})

    lead_facts = [
        fact for fact in market_facts if fact.classification == FactClassification.FACT
    ][:2]
    watch_facts = [
        fact
        for fact in _dedupe_facts([*risk_facts, *policy_facts, *sector_facts])
        if fact.classification not in {FactClassification.OPINION, FactClassification.UNVERIFIED}
        and (
            fact.classification != FactClassification.INFERENCE
            or bool(fact.derived_from_fact_ids)
        )
    ]

    return [
        _section(
            "one_sentence_conclusion",
            _format_fact_lines_or_empty(lead_facts, "今日暂无可结论的硬事实。"),
            lead_facts,
        ),
        _section(
            "market_overview",
            _format_fact_lines_or_empty(market_facts, "暂无指数或市场温度事实。"),
            market_facts,
        ),
        _section(
            "sector_strength",
            _format_fact_lines_or_empty(sector_facts, "暂无板块强弱事实。"),
            sector_facts,
        ),
        _section(
            "fact_opinion_inference",
            _classification_lines(facts),
            facts,
        ),
        _section(
            "next_watchlist",
            _format_watchlist_lines(watch_facts),
            watch_facts,
        ),
        _section(
            "previous_feedback",
            _feedback_summary_lines(previous_feedback_summary),
            [],
        ),
    ]


def _section(section_id: str, lines: list[str], facts: list[AtomicFact]) -> ReportSection:
    return ReportSection(
        section_id=section_id,
        title=section_label(section_id),
        body="\n".join(lines),
        fact_ids=[fact.fact_id for fact in facts],
        status="ok",
        fact_lines=_fact_lines(facts),
    )


def _facts_for_modules(facts: list[AtomicFact], modules: set[str]) -> list[AtomicFact]:
    return [fact for fact in facts if fact.module in modules]


def _dedupe_facts(facts: list[AtomicFact]) -> list[AtomicFact]:
    seen: set[str] = set()
    deduped: list[AtomicFact] = []
    for fact in facts:
        if fact.fact_id in seen:
            continue
        seen.add(fact.fact_id)
        deduped.append(fact)
    return deduped


def _format_fact_lines_or_empty(facts: list[AtomicFact], empty_line: str) -> list[str]:
    if not facts:
        return [f"- {empty_line}"]
    return [_format_fact_line(fact) for fact in facts]


def _feedback_summary_lines(summary: str) -> list[str]:
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if not lines:
        return ["- 暂无历史反馈。"]
    return [f"- {line}" for line in lines]


def _fact_lines(facts: list[AtomicFact]) -> tuple[FactLine, ...]:
    return tuple(
        FactLine(
            fact_id=fact.fact_id,
            classification=fact.classification,
            claim=fact.claim,
            derived_from_fact_ids=fact.derived_from_fact_ids,
        )
        for fact in facts
    )


def _classification_lines(facts: list[AtomicFact]) -> list[str]:
    lines: list[str] = []
    for classification in FactClassification:
        classified_facts = [fact for fact in facts if fact.classification == classification]
        lines.append(f"- **{fact_classification_label(classification)}**")
        if classified_facts:
            lines.extend(f"  {_format_fact_line(fact)}" for fact in classified_facts)
        else:
            lines.append("  - 暂无")
    return lines


def _format_watchlist_lines(facts: list[AtomicFact]) -> list[str]:
    if not facts:
        return ["- 暂无可追踪的下一轮观察事实。"]
    return [
        f"- 待验证：{fact.claim} [{fact.fact_id}]"
        + (
            f"（据 {', '.join(fact.derived_from_fact_ids)}）"
            if fact.derived_from_fact_ids
            else ""
        )
        for fact in facts
    ]


def _format_fact_line(fact: AtomicFact) -> str:
    label = fact_classification_label(fact.classification)
    return f"- **{label}** {fact.claim} [{fact.fact_id}]"


def _format_source_line(index: int, fact: AtomicFact) -> str:
    published_at = fact.published_at.isoformat() if fact.published_at else "unknown"
    return (
        f"- [{index}] [{fact.fact_id}] {fact.source_name} ({fact.source_type.value}): "
        f"{fact.source_url}; published={published_at}"
    )
