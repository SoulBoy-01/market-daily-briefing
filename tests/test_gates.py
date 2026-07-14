from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from market_briefing.domain import (
    MarketIndexRecord,
    MarketTemperatureRecord,
    OfficialCheckStatus,
    SectorSnapshotRecord,
)
from market_briefing.evaluation import load_golden_cases
from market_briefing.gates import CORE_INDEX_SYMBOLS, evaluate_after_close_gate


EVALUATED_AT = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)


def _indices(trade_date: date = date(2026, 7, 2)) -> list[MarketIndexRecord]:
    values = {
        "000001.SH": ("3350.10", "0.45"),
        "399001.SZ": ("10540.20", "0.40"),
        "399006.SZ": ("2152.10", "0.48"),
    }
    return [
        MarketIndexRecord(
            provider_id=provider_id,
            trade_date=trade_date,
            symbol=symbol,
            close=Decimal(close),
            change_pct=Decimal(change_pct),
            evidence_id=f"{provider_id}-{symbol}",
        )
        for provider_id in ("provider-a", "provider-b")
        for symbol, (close, change_pct) in values.items()
    ]


def _temperature(trade_date: date = date(2026, 7, 2)) -> MarketTemperatureRecord:
    return MarketTemperatureRecord(
        provider_id="temperature-provider",
        trade_date=trade_date,
        total_turnover_cny=Decimal("1020000000000"),
        turnover_change_pct=Decimal("4.1"),
        advancing_count=3090,
        declining_count=1900,
        evidence_id="temperature-evidence",
    )


def _sectors(trade_date: date = date(2026, 7, 2)) -> SectorSnapshotRecord:
    return SectorSnapshotRecord(
        provider_id="sector-provider",
        trade_date=trade_date,
        taxonomy="synthetic-industry-v1",
        evidence_id="sector-evidence",
    )


def _evaluate(
    *,
    indices=None,
    temperature=_temperature(),
    sectors=_sectors(),
    official_checks=(OfficialCheckStatus.CHECKED_NO_UPDATES,),
    report_date=date(2026, 7, 2),
    is_trading_day=True,
):
    return evaluate_after_close_gate(
        run_id="run-gate",
        report_date=report_date,
        core_indices=_indices() if indices is None else indices,
        market_temperature=temperature,
        sector_snapshot=sectors,
        official_checks=official_checks,
        is_trading_day=is_trading_day,
        evaluated_at=EVALUATED_AT,
    )


def test_core_index_symbols_are_fixed_by_product_contract():
    assert CORE_INDEX_SYMBOLS == ("000001.SH", "399001.SZ", "399006.SZ")


def test_complete_fresh_after_close_input_passes_gate():
    result = _evaluate()

    assert result.publishable is True
    assert result.blocking_errors == ()
    assert result.warnings == ()


def test_non_trading_day_is_explicitly_rejected():
    result = _evaluate(is_trading_day=False)

    assert result.publishable is False
    assert [error.code for error in result.blocking_errors] == ["not_trading_day"]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda rows: [row for row in rows if row.symbol != "399006.SZ"], "core_index_missing"),
        (lambda rows: [*rows, rows[0]], "core_index_duplicate"),
        (
            lambda rows: [replace(row, trade_date=date(2026, 7, 1)) for row in rows],
            "core_index_stale",
        ),
        (
            lambda rows: [replace(rows[0], close=Decimal("NaN")), *rows[1:]],
            "core_index_invalid_value",
        ),
        (
            lambda rows: [replace(rows[0], change_pct=Decimal("Infinity")), *rows[1:]],
            "core_index_invalid_value",
        ),
    ],
)
def test_core_index_integrity_failures_block_publication(mutate, expected_code):
    result = _evaluate(indices=mutate(_indices()))

    assert result.publishable is False
    assert expected_code in [error.code for error in result.blocking_errors]


def test_missing_degradable_modules_emit_structured_warnings_without_blocking():
    result = _evaluate(temperature=None, sectors=None)

    assert result.publishable is True
    assert [warning.message for warning in result.warnings] == [
        "市场温度数据缺失",
        "板块数据缺失",
    ]
    assert [warning.module for warning in result.warnings] == [
        "market_temperature",
        "sector_moves",
    ]
    assert [warning.warning_id for warning in result.warnings] == [
        "warning-run-gate-market-temperature-missing",
        "warning-run-gate-sector-missing",
    ]


def test_stale_degradable_modules_warn_and_official_candidate_blocks():
    result = _evaluate(
        temperature=_temperature(date(2026, 7, 1)),
        sectors=_sectors(date(2026, 7, 1)),
        official_checks=(OfficialCheckStatus.CANDIDATES_FOUND,),
    )

    assert [error.code for error in result.blocking_errors] == ["pending_official_review"]
    assert [warning.message for warning in result.warnings] == [
        "市场温度数据不是报告日期",
        "板块数据不是报告日期",
    ]


def test_official_check_failure_is_degradable_warning():
    result = _evaluate(official_checks=(OfficialCheckStatus.CHECK_FAILED,))

    assert result.publishable is True
    assert [warning.warning_id for warning in result.warnings] == [
        "warning-run-gate-official-check-failed"
    ]


def test_nine_golden_cases_match_gate_outcomes_before_reconciliation():
    cases = [
        case
        for case in load_golden_cases(Path("tests/golden/cases"))
        if case.case_id != "source-conflict"
    ]

    for case in cases:
        result = evaluate_after_close_gate(
            run_id=case.case_id,
            report_date=case.report_date,
            core_indices=[MarketIndexRecord(**item.model_dump()) for item in case.inputs.core_indices],
            market_temperature=(
                MarketTemperatureRecord(**case.inputs.market_temperature.model_dump())
                if case.inputs.market_temperature
                else None
            ),
            sector_snapshot=(
                SectorSnapshotRecord(
                    provider_id=case.inputs.sector_snapshot.provider_id,
                    trade_date=case.inputs.sector_snapshot.trade_date,
                    taxonomy=case.inputs.sector_snapshot.taxonomy,
                    evidence_id=case.inputs.sector_snapshot.evidence_id,
                )
                if case.inputs.sector_snapshot
                else None
            ),
            official_checks=tuple(
                OfficialCheckStatus(check.result) for check in case.inputs.official_checks
            ),
            is_trading_day=True,
            evaluated_at=EVALUATED_AT,
        )

        assert result.publishable == case.expected.publishable, case.case_id
        assert tuple(error.code for error in result.blocking_errors) == (
            case.expected.blocking_error_codes
        ), case.case_id
        assert tuple(_warning_code(warning.warning_id) for warning in result.warnings) == (
            case.expected.warning_codes
        ), case.case_id


def _warning_code(warning_id: str) -> str:
    return warning_id.split("-", maxsplit=3)[-1].replace("-", "_")
