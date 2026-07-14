from __future__ import annotations

from dataclasses import dataclass
import re

from market_briefing.domain import AtomicFact, FactClassification, ReportSection


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

SECTION_CLASS_RULES = {
    "one_sentence_conclusion": {
        "allow": {FactClassification.FACT},
    },
    "market_overview": {
        "deny": {FactClassification.UNVERIFIED},
        "inference_must_have_derivation": True,
    },
    "sector_strength": {
        "deny": {FactClassification.UNVERIFIED},
        "inference_must_have_derivation": True,
    },
    # fact_opinion_inference is intentionally unrestricted: it displays all
    # classifications side by side as an audit view.
    "next_watchlist": {
        "deny": {FactClassification.OPINION, FactClassification.UNVERIFIED},
        "inference_must_have_derivation": True,
    },
    "today_watchpoints": {
        "deny": {FactClassification.OPINION, FactClassification.UNVERIFIED},
        "inference_must_have_derivation": True,
    },
}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_report_sections(
    sections: list[ReportSection],
    facts: list[AtomicFact],
) -> ValidationResult:
    fact_by_id = {fact.fact_id: fact for fact in facts}
    fact_ids = set(fact_by_id)
    errors: list[str] = []

    for section in sections:
        for fact_id in _section_fact_ids(section):
            if fact_id not in fact_ids:
                errors.append(f"section {section.section_id} cites missing fact_id {fact_id}")
                continue

            fact = fact_by_id[fact_id]
            errors.extend(_classification_errors(section.section_id, fact, fact_ids))

        normalized_text = f"{section.title}\n{section.body}".casefold()
        for phrase in BANNED_PHRASES:
            if phrase.casefold() in normalized_text:
                errors.append(f"section {section.section_id} contains banned phrase {phrase}")

    return ValidationResult(ok=not errors, errors=errors)


def validate_real_publishable_facts(facts: list[AtomicFact]) -> ValidationResult:
    fact_by_id = {fact.fact_id: fact for fact in facts}
    errors: list[str] = []
    for fact in facts:
        if fact.classification == FactClassification.UNVERIFIED:
            errors.append(f"real publication rejects UNVERIFIED fact {fact.fact_id}")
        if fact.classification != FactClassification.INFERENCE:
            continue
        if not fact.derived_from_fact_ids:
            errors.append(f"real inference {fact.fact_id} has no derived facts")
            continue
        for derived_fact_id in fact.derived_from_fact_ids:
            derived_fact = fact_by_id.get(derived_fact_id)
            if derived_fact is None:
                errors.append(
                    f"real inference {fact.fact_id} derives from missing fact_id "
                    f"{derived_fact_id}"
                )
            elif derived_fact.classification != FactClassification.FACT:
                errors.append(
                    f"real inference {fact.fact_id} derives from non-FACT fact_id "
                    f"{derived_fact_id}"
                )
    return ValidationResult(ok=not errors, errors=errors)


def _classification_errors(
    section_id: str,
    fact: AtomicFact,
    fact_ids: set[str],
) -> list[str]:
    rule = SECTION_CLASS_RULES.get(section_id)
    if not rule:
        return []

    errors: list[str] = []
    allowed = rule.get("allow")
    denied = rule.get("deny", set())
    if allowed is not None and fact.classification not in allowed:
        errors.append(
            f"section {section_id} cites {fact.fact_id} "
            f"with disallowed classification {fact.classification.value}"
        )
    if fact.classification in denied:
        errors.append(
            f"section {section_id} cites {fact.fact_id} "
            f"with disallowed classification {fact.classification.value}"
        )
    if (
        rule.get("inference_must_have_derivation")
        and fact.classification == FactClassification.INFERENCE
    ):
        if not fact.derived_from_fact_ids:
            errors.append(f"section {section_id} cites inference {fact.fact_id} without derived facts")
        for derived_fact_id in fact.derived_from_fact_ids:
            if derived_fact_id not in fact_ids:
                errors.append(
                    f"section {section_id} cites inference {fact.fact_id} "
                    f"derived from missing fact_id {derived_fact_id}"
                )
    return errors


def _section_fact_ids(section: ReportSection) -> tuple[str, ...]:
    seen: set[str] = set()
    fact_ids: list[str] = []
    fact_line_ids = tuple(fact_line.fact_id for fact_line in section.fact_lines)
    for fact_id in (*section.fact_ids, *fact_line_ids, *FACT_CITATION_RE.findall(section.body)):
        if fact_id not in seen:
            seen.add(fact_id)
            fact_ids.append(fact_id)
    return tuple(fact_ids)
