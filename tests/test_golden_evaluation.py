from pathlib import Path

import pytest
from pydantic import ValidationError

from market_briefing.evaluation import (
    EvaluationOutcome,
    GoldenCase,
    evaluate_golden_case,
    load_golden_cases,
    run_golden_evaluation,
)


GOLDEN_CASES_DIR = Path("tests/golden/cases")


def test_loads_ten_representative_cases_offline():
    cases = load_golden_cases(GOLDEN_CASES_DIR)

    assert [case.scenario for case in cases] == [
        "普涨",
        "普跌",
        "放量",
        "缩量",
        "板块分化",
        "有官方事项",
        "无官方新增",
        "官方来源失败",
        "双源冲突",
        "过期数据",
    ]
    assert len({case.case_id for case in cases}) == 10


def test_every_golden_input_references_local_case_evidence():
    for case in load_golden_cases(GOLDEN_CASES_DIR):
        evidence_ids = {item.evidence_id for item in case.evidence}
        referenced_ids = {
            *(observation.evidence_id for observation in case.inputs.core_indices),
            *(check.evidence_id for check in case.inputs.official_checks),
        }
        if case.inputs.market_temperature:
            referenced_ids.add(case.inputs.market_temperature.evidence_id)
        if case.inputs.sector_snapshot:
            referenced_ids.add(case.inputs.sector_snapshot.evidence_id)

        assert referenced_ids == evidence_ids, case.case_id
        assert all(
            item.snapshot_ref.startswith(f"case://{case.case_id}/") for item in case.evidence
        )


def test_evaluator_reports_each_mismatch_with_case_date_metric_source_and_gate():
    case = load_golden_cases(GOLDEN_CASES_DIR)[0]

    errors = evaluate_golden_case(
        case,
        EvaluationOutcome(
            publishable=False,
            blocking_error_codes=("core_index_missing",),
            warning_codes=("sector_missing",),
        ),
    )

    assert [error.metric for error in errors] == [
        "publishable",
        "blocking_error_codes",
        "warning_codes",
    ]
    assert all(error.case_id == "broad-rise" for error in errors)
    assert all(error.report_date.isoformat() == "2026-06-29" for error in errors)
    assert all(error.source == "golden-expected" for error in errors)
    assert [error.gate for error in errors] == [
        "publication",
        "core_index_missing",
        "sector_missing",
    ]


def test_evaluator_returns_no_errors_for_expected_outcome():
    for case in load_golden_cases(GOLDEN_CASES_DIR):
        actual = EvaluationOutcome(
            publishable=case.expected.publishable,
            blocking_error_codes=case.expected.blocking_error_codes,
            warning_codes=case.expected.warning_codes,
        )

        assert evaluate_golden_case(case, actual) == []


def test_suite_runner_aggregates_case_level_errors():
    cases = load_golden_cases(GOLDEN_CASES_DIR)[:2]

    errors = run_golden_evaluation(
        cases,
        lambda case: EvaluationOutcome(
            publishable=False,
            blocking_error_codes=("injected_error",),
            warning_codes=case.expected.warning_codes,
        ),
    )

    assert {error.case_id for error in errors} == {"broad-rise", "broad-fall"}
    assert {error.metric for error in errors} == {"publishable", "blocking_error_codes"}


def test_golden_schema_rejects_unknown_fields():
    case = load_golden_cases(GOLDEN_CASES_DIR)[0]
    payload = case.model_dump(mode="json")
    payload["unexpected"] = "schema drift"

    with pytest.raises(ValidationError):
        GoldenCase.model_validate(payload)
