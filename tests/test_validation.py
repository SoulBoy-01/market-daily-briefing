from datetime import datetime, timezone

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    ReportSection,
    ReportType,
    SourceType,
)
from market_briefing.validation import validate_report_sections


def _fact(fact_id: str, claim: str) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim=claim,
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        used_in_sections=["market_indices"],
    )


def test_validation_accepts_sections_that_cite_existing_facts():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "market_indices",
            "指数表现",
            "上证指数收涨。[fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is True
    assert result.errors == []


def test_validation_rejects_missing_fact_id():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "market_indices",
            "指数表现",
            "引用了不存在事实。[fact-999]",
            ["fact-999"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert result.errors == ["section market_indices cites missing fact_id fact-999"]


def test_validation_rejects_missing_fact_id_cited_only_in_body():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "market_indices",
            "指数表现",
            "正文引用了不存在事实。[fact-999]",
            [],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert result.errors == ["section market_indices cites missing fact_id fact-999"]


def test_validation_rejects_banned_investment_advice_language():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "risk_points",
            "风险提示",
            "建议买入相关个股。[fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section risk_points contains banned phrase 建议买入" in result.errors


def test_validation_rejects_banned_investment_advice_language_in_title():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "risk_points",
            "目标价风险提示",
            "正文只引用已有事实。[fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section risk_points contains banned phrase 目标价" in result.errors


def test_validation_rejects_english_position_advice_language():
    facts = [_fact("fact-001", "The Shanghai Composite closed higher.")]
    sections = [
        ReportSection(
            "risk_points",
            "Risk points",
            "This is position advice for the next session. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section risk_points contains banned phrase position advice" in result.errors
