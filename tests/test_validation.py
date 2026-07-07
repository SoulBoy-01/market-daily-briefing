from datetime import datetime, timezone

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FactLine,
    ReportSection,
    ReportType,
    SourceType,
)
from market_briefing.validation import validate_report_sections


def _fact(
    fact_id: str,
    claim: str,
    classification: FactClassification = FactClassification.FACT,
    derived_from_fact_ids: tuple[str, ...] = (),
) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim=claim,
        classification=classification,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        derived_from_fact_ids=derived_from_fact_ids,
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


def test_validation_rejects_missing_fact_id_cited_only_in_fact_lines():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [
        ReportSection(
            "market_indices",
            "指数表现",
            "结构化事实行引用了不存在事实。",
            [],
            "ok",
            fact_lines=[
                FactLine(
                    fact_id="fact-999",
                    classification=FactClassification.FACT,
                    claim="Missing structured fact.",
                )
            ],
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


def test_validation_rejects_opinion_in_one_sentence_conclusion():
    facts = [_fact("fact-001", "券商认为风险偏好修复。", FactClassification.OPINION)]
    sections = [
        ReportSection(
            "one_sentence_conclusion",
            "今日一句话结论",
            "券商认为风险偏好修复。[fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert (
        "section one_sentence_conclusion cites fact-001 with disallowed classification opinion"
        in result.errors
    )


def test_validation_rejects_opinion_and_unrooted_inference_in_watchlist():
    facts = [
        _fact("fact-001", "券商认为风险偏好修复。", FactClassification.OPINION),
        _fact("fact-002", "系统归纳需要继续验证。", FactClassification.INFERENCE),
    ]
    sections = [
        ReportSection(
            "next_watchlist",
            "下一轮观察清单",
            "待验证：券商认为风险偏好修复。[fact-001]\n待验证：系统归纳需要继续验证。[fact-002]",
            ["fact-001", "fact-002"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section next_watchlist cites fact-001 with disallowed classification opinion" in result.errors
    assert "section next_watchlist cites inference fact-002 without derived facts" in result.errors


def test_validation_rejects_unverified_in_watchlist():
    facts = [
        _fact("fact-001", "Unverified market rumor.", FactClassification.UNVERIFIED),
    ]
    sections = [
        ReportSection(
            "next_watchlist",
            "下一轮观察清单",
            "待验证：Unverified market rumor. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section next_watchlist cites fact-001 with disallowed classification unverified" in result.errors


def test_validation_rejects_unverified_in_market_overview():
    facts = [
        _fact("fact-001", "Unverified index rumor.", FactClassification.UNVERIFIED),
    ]
    sections = [
        ReportSection(
            "market_overview",
            "市场全貌",
            "Unverified index rumor. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section market_overview cites fact-001 with disallowed classification unverified" in result.errors


def test_validation_rejects_unrooted_inference_in_market_overview():
    facts = [
        _fact("fact-001", "Unrooted market inference.", FactClassification.INFERENCE),
    ]
    sections = [
        ReportSection(
            "market_overview",
            "市场全貌",
            "Unrooted market inference. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section market_overview cites inference fact-001 without derived facts" in result.errors


def test_validation_rejects_unverified_in_sector_strength():
    facts = [
        _fact("fact-001", "Unverified sector rumor.", FactClassification.UNVERIFIED),
    ]
    sections = [
        ReportSection(
            "sector_strength",
            "强弱板块",
            "Unverified sector rumor. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section sector_strength cites fact-001 with disallowed classification unverified" in result.errors


def test_validation_rejects_unrooted_inference_in_sector_strength():
    facts = [
        _fact("fact-001", "Unrooted sector inference.", FactClassification.INFERENCE),
    ]
    sections = [
        ReportSection(
            "sector_strength",
            "强弱板块",
            "Unrooted sector inference. [fact-001]",
            ["fact-001"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section sector_strength cites inference fact-001 without derived facts" in result.errors


def test_validation_rejects_inference_derived_from_missing_fact():
    facts = [
        _fact(
            "fact-002",
            "系统归纳需要继续验证。",
            FactClassification.INFERENCE,
            derived_from_fact_ids=("fact-missing",),
        )
    ]
    sections = [
        ReportSection(
            "next_watchlist",
            "下一轮观察清单",
            "待验证：系统归纳需要继续验证。[fact-002]",
            ["fact-002"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section next_watchlist cites inference fact-002 derived from missing fact_id fact-missing" in result.errors


def test_validation_allows_fact_with_derived_fact_ids():
    facts = [
        _fact("fact-001", "上证指数收涨。"),
        _fact(
            "fact-002",
            "市场温度由指数和成交背景合成。",
            FactClassification.FACT,
            derived_from_fact_ids=("fact-001",),
        ),
    ]
    sections = [
        ReportSection(
            "one_sentence_conclusion",
            "今日一句话结论",
            "市场温度由指数和成交背景合成。[fact-002]",
            ["fact-002"],
            "ok",
        )
    ]

    result = validate_report_sections(sections, facts)

    assert result.ok is True
    assert result.errors == []
