from datetime import datetime, timezone

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    ReportSection,
    ReportType,
    SourceType,
)
from market_briefing.llm import LLMProvider, generate_with_optional_llm


class BadProvider(LLMProvider):
    def generate_sections(
        self, facts: list[AtomicFact], feedback_summary: str
    ) -> list[ReportSection]:
        return [
            ReportSection(
                section_id="risk_points",
                title="风险提示",
                body="建议买入某公司股票。[fact-missing]",
                fact_ids=["fact-missing"],
                status="ok",
            )
        ]


class GoodProvider(LLMProvider):
    def generate_sections(
        self, facts: list[AtomicFact], feedback_summary: str
    ) -> list[ReportSection]:
        return [
            ReportSection(
                section_id="market_indices",
                title="指数表现",
                body="上证指数收涨。[fact-001]",
                fact_ids=["fact-001"],
                status="ok",
            )
        ]


def _fact() -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="上证指数收涨。",
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


def test_bad_llm_output_falls_back_to_template_report():
    result = generate_with_optional_llm(
        provider=BadProvider(),
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=[_fact()],
        feedback_summary="",
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert result.used_fallback is True
    assert result.validation_errors == [
        "section risk_points cites missing fact_id fact-missing",
        "section risk_points contains banned phrase 建议买入",
    ]
    assert result.report.sections[0].section_id == "market_indices"


def test_good_llm_output_is_used():
    result = generate_with_optional_llm(
        provider=GoodProvider(),
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=[_fact()],
        feedback_summary="",
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert result.used_fallback is False
    assert result.report.sections[0].body == "上证指数收涨。[fact-001]"
