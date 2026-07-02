from __future__ import annotations

from dataclasses import dataclass
import re

from market_briefing.domain import AtomicFact, ReportSection


BANNED_PHRASES = (
    "建议买入",
    "建议卖出",
    "应买入",
    "应卖出",
    "目标价",
    "仓位建议",
    "buy recommendation",
    "sell recommendation",
    "target price",
    "position advice",
    "position sizing",
)

FACT_CITATION_RE = re.compile(r"\[(fact[-_\w:.]+)\]")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_report_sections(
    sections: list[ReportSection],
    facts: list[AtomicFact],
) -> ValidationResult:
    fact_ids = {fact.fact_id for fact in facts}
    errors: list[str] = []

    for section in sections:
        for fact_id in _section_fact_ids(section):
            if fact_id not in fact_ids:
                errors.append(f"section {section.section_id} cites missing fact_id {fact_id}")

        normalized_body = section.body.casefold()
        for phrase in BANNED_PHRASES:
            if phrase.casefold() in normalized_body:
                errors.append(f"section {section.section_id} contains banned phrase {phrase}")

    return ValidationResult(ok=not errors, errors=errors)


def _section_fact_ids(section: ReportSection) -> tuple[str, ...]:
    seen: set[str] = set()
    fact_ids: list[str] = []
    for fact_id in (*section.fact_ids, *FACT_CITATION_RE.findall(section.body)):
        if fact_id not in seen:
            seen.add(fact_id)
            fact_ids.append(fact_id)
    return tuple(fact_ids)
