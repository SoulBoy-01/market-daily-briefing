from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from market_briefing.domain import (
    MarketIndexRecord,
    MarketTemperatureRecord,
    OfficialCheckStatus,
    SectorSnapshotRecord,
)
from market_briefing.evaluation import load_golden_cases
from market_briefing.gates import evaluate_after_close_gate
from market_briefing.reconciliation import (
    CHANGE_PCT_DECIMAL_PLACES,
    CLOSE_DECIMAL_PLACES,
    reconcile_core_indices,
)


EVALUATED_AT = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)


def _records() -> list[MarketIndexRecord]:
    values = {
        "000001.SH": ("3350.104", "0.454"),
        "399001.SZ": ("10540.204", "0.404"),
        "399006.SZ": ("2152.104", "0.484"),
    }
    records: list[MarketIndexRecord] = []
    for provider_id in ("provider-a", "provider-b"):
        for symbol, (close, change_pct) in values.items():
            records.append(
                MarketIndexRecord(
                    provider_id=provider_id,
                    trade_date=datetime(2026, 7, 2).date(),
                    symbol=symbol,
                    close=Decimal(close)
                    + (Decimal("0.0001") if provider_id == "provider-b" else 0),
                    change_pct=Decimal(change_pct),
                    evidence_id=f"evidence-{provider_id}-{symbol}",
                )
            )
    return records


def test_reconciliation_accepts_two_independent_sources_at_display_precision():
    result = reconcile_core_indices(_records())

    assert result.passed is True
    assert result.blocking_errors == ()
    assert result.diagnostics == ()
    assert len(result.reconciled_indices) == 3
    assert result.close_decimal_places == CLOSE_DECIMAL_PLACES == 2
    assert result.change_pct_decimal_places == CHANGE_PCT_DECIMAL_PLACES == 2
    first = result.reconciled_indices[0]
    assert first.symbol == "000001.SH"
    assert first.close == Decimal("3350.10")
    assert first.change_pct == Decimal("0.45")
    assert first.provider_ids == ("provider-a", "provider-b")
    assert len(first.evidence_ids) == 2


def test_same_provider_id_cannot_satisfy_dual_source_requirement():
    records = [replace(record, provider_id="same-provider") for record in _records()]

    result = reconcile_core_indices(records)

    assert result.passed is False
    assert [error.code for error in result.blocking_errors] == [
        "core_index_provider_not_independent"
    ]
    assert result.reconciled_indices == ()


def test_incomplete_provider_set_blocks_reconciliation():
    records = [
        record
        for record in _records()
        if not (record.provider_id == "provider-b" and record.symbol == "399006.SZ")
    ]

    result = reconcile_core_indices(records)

    assert result.passed is False
    assert [error.code for error in result.blocking_errors] == [
        "core_index_source_incomplete"
    ]
    assert result.reconciled_indices == ()


def test_duplicate_provider_symbol_is_rejected_without_selecting_a_record():
    records = _records()

    result = reconcile_core_indices([*records, records[0]])

    assert result.passed is False
    assert [error.code for error in result.blocking_errors] == [
        "core_index_source_duplicate"
    ]
    assert result.reconciled_indices == ()


def test_conflict_returns_diagnostics_without_selecting_or_averaging_value():
    records = [
        (
            replace(record, close=Decimal("3351.10"))
            if record.provider_id == "provider-b" and record.symbol == "000001.SH"
            else record
        )
        for record in _records()
    ]

    result = reconcile_core_indices(records)

    assert result.passed is False
    assert [error.code for error in result.blocking_errors] == [
        "core_index_source_conflict"
    ]
    assert result.reconciled_indices == ()
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.symbol == "000001.SH"
    assert diagnostic.field == "close"
    assert diagnostic.provider_values == (
        ("provider-a", "3350.10"),
        ("provider-b", "3351.10"),
    )


def test_all_ten_golden_cases_match_combined_gate_and_reconciliation_contracts():
    for case in load_golden_cases(Path("tests/golden/cases")):
        records = [MarketIndexRecord(**item.model_dump()) for item in case.inputs.core_indices]
        reconciliation = reconcile_core_indices(records)
        gate = evaluate_after_close_gate(
            run_id=case.case_id,
            report_date=case.report_date,
            core_indices=records,
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
        error_codes = (
            *(error.code for error in reconciliation.blocking_errors),
            *(error.code for error in gate.blocking_errors),
        )
        warning_codes = tuple(_warning_code(warning.warning_id) for warning in gate.warnings)

        assert (not error_codes) == case.expected.publishable, case.case_id
        assert error_codes == case.expected.blocking_error_codes, case.case_id
        assert warning_codes == case.expected.warning_codes, case.case_id


def _warning_code(warning_id: str) -> str:
    case_ids = {case.case_id for case in load_golden_cases(Path("tests/golden/cases"))}
    prefix = next(
        f"warning-{case_id}-"
        for case_id in case_ids
        if warning_id.startswith(f"warning-{case_id}-")
    )
    return warning_id.removeprefix(prefix).replace("-", "_")
