from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from market_briefing.domain import AtomicFact, Report, ReportSection, ReportType
from market_briefing.reporting import build_report
from market_briefing.validation import validate_report_sections


class LLMProvider(Protocol):
    def generate_sections(
        self, facts: list[AtomicFact], feedback_summary: str
    ) -> list[ReportSection]: ...


@dataclass(frozen=True)
class GeneratedReportResult:
    report: Report
    used_fallback: bool
    validation_errors: list[str]


def generate_with_optional_llm(
    provider: LLMProvider | None,
    report_id: str,
    run_id: str,
    report_date: str,
    report_type: ReportType,
    facts: list[AtomicFact],
    feedback_summary: str,
    markdown_path: str,
    html_path: str,
    fact_ledger_path: str,
) -> GeneratedReportResult:
    fallback = build_report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        facts=facts,
        markdown_path=markdown_path,
        html_path=html_path,
        fact_ledger_path=fact_ledger_path,
    )

    if provider is None:
        return GeneratedReportResult(
            report=fallback,
            used_fallback=True,
            validation_errors=[],
        )

    try:
        sections = provider.generate_sections(facts, feedback_summary)
    except Exception as exc:
        return GeneratedReportResult(
            report=fallback,
            used_fallback=True,
            validation_errors=[f"provider failed: {exc}"],
        )

    if not isinstance(sections, list) or not all(
        isinstance(section, ReportSection) for section in sections
    ):
        return GeneratedReportResult(
            report=fallback,
            used_fallback=True,
            validation_errors=["provider returned invalid sections"],
        )

    validation = validate_report_sections(sections, facts)
    if not validation.ok:
        return GeneratedReportResult(
            report=fallback,
            used_fallback=True,
            validation_errors=validation.errors,
        )

    report = Report(
        report_id=fallback.report_id,
        run_id=fallback.run_id,
        report_date=fallback.report_date,
        report_type=fallback.report_type,
        title=fallback.title,
        sections=sections,
        markdown_path=fallback.markdown_path,
        html_path=fallback.html_path,
        fact_ledger_path=fallback.fact_ledger_path,
    )

    return GeneratedReportResult(
        report=report,
        used_fallback=False,
        validation_errors=[],
    )
