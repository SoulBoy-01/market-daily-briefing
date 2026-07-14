from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldenIndexObservation(FrozenModel):
    provider_id: str
    trade_date: date
    symbol: str
    close: Decimal
    change_pct: Decimal
    evidence_id: str


class GoldenMarketTemperature(FrozenModel):
    provider_id: str
    trade_date: date
    total_turnover_cny: Decimal
    turnover_change_pct: Decimal
    advancing_count: int
    declining_count: int
    evidence_id: str


class GoldenSectorMove(FrozenModel):
    name: str
    change_pct: Decimal


class GoldenSectorSnapshot(FrozenModel):
    provider_id: str
    trade_date: date
    taxonomy: str
    leaders: tuple[GoldenSectorMove, ...]
    laggards: tuple[GoldenSectorMove, ...]
    evidence_id: str


class GoldenOfficialCheck(FrozenModel):
    source_name: str
    result: Literal["checked_no_updates", "candidates_found", "check_failed"]
    evidence_id: str


class GoldenEvidenceReference(FrozenModel):
    evidence_id: str
    source_name: str
    snapshot_ref: str


class GoldenInputs(FrozenModel):
    core_indices: tuple[GoldenIndexObservation, ...]
    market_temperature: GoldenMarketTemperature | None
    sector_snapshot: GoldenSectorSnapshot | None
    official_checks: tuple[GoldenOfficialCheck, ...]


class GoldenExpected(FrozenModel):
    publishable: bool
    blocking_error_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()


class GoldenCase(FrozenModel):
    case_id: str
    scenario: str
    report_date: date
    inputs: GoldenInputs
    expected: GoldenExpected
    evidence: tuple[GoldenEvidenceReference, ...]


class EvaluationOutcome(FrozenModel):
    publishable: bool
    blocking_error_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()


class EvaluationError(FrozenModel):
    case_id: str
    report_date: date
    metric: str
    source: str
    gate: str
    expected: object
    actual: object


def load_golden_cases(cases_dir: Path) -> list[GoldenCase]:
    return [
        GoldenCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(cases_dir.glob("*.json"))
    ]


def evaluate_golden_case(
    case: GoldenCase,
    actual: EvaluationOutcome,
) -> list[EvaluationError]:
    errors: list[EvaluationError] = []
    if actual.publishable != case.expected.publishable:
        errors.append(
            _evaluation_error(
                case,
                metric="publishable",
                gate="publication",
                expected=case.expected.publishable,
                actual=actual.publishable,
            )
        )
    if actual.blocking_error_codes != case.expected.blocking_error_codes:
        errors.append(
            _evaluation_error(
                case,
                metric="blocking_error_codes",
                gate=_first_difference(
                    case.expected.blocking_error_codes,
                    actual.blocking_error_codes,
                    default="blocking_errors",
                ),
                expected=case.expected.blocking_error_codes,
                actual=actual.blocking_error_codes,
            )
        )
    if actual.warning_codes != case.expected.warning_codes:
        errors.append(
            _evaluation_error(
                case,
                metric="warning_codes",
                gate=_first_difference(
                    case.expected.warning_codes,
                    actual.warning_codes,
                    default="warnings",
                ),
                expected=case.expected.warning_codes,
                actual=actual.warning_codes,
            )
        )
    return errors


def run_golden_evaluation(
    cases: list[GoldenCase],
    evaluate: Callable[[GoldenCase], EvaluationOutcome],
) -> list[EvaluationError]:
    return [
        error
        for case in cases
        for error in evaluate_golden_case(case, evaluate(case))
    ]


def _evaluation_error(
    case: GoldenCase,
    *,
    metric: str,
    gate: str,
    expected: object,
    actual: object,
) -> EvaluationError:
    return EvaluationError(
        case_id=case.case_id,
        report_date=case.report_date,
        metric=metric,
        source="golden-expected",
        gate=gate,
        expected=expected,
        actual=actual,
    )


def _first_difference(
    expected: tuple[str, ...],
    actual: tuple[str, ...],
    *,
    default: str,
) -> str:
    return next(
        (code for code in (*expected, *actual) if code not in expected or code not in actual),
        expected[0] if expected else actual[0] if actual else default,
    )
