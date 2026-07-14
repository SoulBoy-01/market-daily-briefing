from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from market_briefing.domain import MarketIndexRecord
from market_briefing.gates import CORE_INDEX_SYMBOLS, GateError


CLOSE_DECIMAL_PLACES = 2
CHANGE_PCT_DECIMAL_PLACES = 2


@dataclass(frozen=True)
class ReconciledIndex:
    trade_date: date
    symbol: str
    close: Decimal
    change_pct: Decimal
    provider_ids: tuple[str, str]
    evidence_ids: tuple[str, str]


@dataclass(frozen=True)
class ReconciliationDiagnostic:
    symbol: str
    field: str
    provider_values: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ReconciliationResult:
    reconciled_indices: tuple[ReconciledIndex, ...]
    blocking_errors: tuple[GateError, ...]
    diagnostics: tuple[ReconciliationDiagnostic, ...]
    close_decimal_places: int = CLOSE_DECIMAL_PLACES
    change_pct_decimal_places: int = CHANGE_PCT_DECIMAL_PLACES

    @property
    def passed(self) -> bool:
        return not self.blocking_errors


def reconcile_core_indices(records: list[MarketIndexRecord]) -> ReconciliationResult:
    provider_ids = tuple(sorted({record.provider_id for record in records}))
    if len(provider_ids) != 2:
        return _failed_result(
            "core_index_provider_not_independent",
            "核心指数必须来自两个独立提供方",
        )

    by_provider_symbol = {
        (record.provider_id, record.symbol): record for record in records
    }
    if len(by_provider_symbol) != len(records):
        return _failed_result(
            "core_index_source_duplicate",
            "同一提供方的核心指数记录不得重复",
        )
    expected_keys = {
        (provider_id, symbol)
        for provider_id in provider_ids
        for symbol in CORE_INDEX_SYMBOLS
    }
    if set(by_provider_symbol) != expected_keys:
        return _failed_result(
            "core_index_source_incomplete",
            "两个提供方都必须完整覆盖三个核心指数",
        )

    reconciled: list[ReconciledIndex] = []
    diagnostics: list[ReconciliationDiagnostic] = []
    for symbol in CORE_INDEX_SYMBOLS:
        left = by_provider_symbol[(provider_ids[0], symbol)]
        right = by_provider_symbol[(provider_ids[1], symbol)]
        if left.trade_date != right.trade_date:
            diagnostics.append(
                ReconciliationDiagnostic(
                    symbol=symbol,
                    field="trade_date",
                    provider_values=(
                        (left.provider_id, left.trade_date.isoformat()),
                        (right.provider_id, right.trade_date.isoformat()),
                    ),
                )
            )
            continue
        close_values = (
            _quantize(left.close, CLOSE_DECIMAL_PLACES),
            _quantize(right.close, CLOSE_DECIMAL_PLACES),
        )
        change_values = (
            _quantize(left.change_pct, CHANGE_PCT_DECIMAL_PLACES),
            _quantize(right.change_pct, CHANGE_PCT_DECIMAL_PLACES),
        )
        if close_values[0] != close_values[1]:
            diagnostics.append(
                _numeric_diagnostic(symbol, "close", provider_ids, close_values)
            )
        if change_values[0] != change_values[1]:
            diagnostics.append(
                _numeric_diagnostic(symbol, "change_pct", provider_ids, change_values)
            )
        if diagnostics and diagnostics[-1].symbol == symbol:
            continue
        reconciled.append(
            ReconciledIndex(
                trade_date=left.trade_date,
                symbol=symbol,
                close=close_values[0],
                change_pct=change_values[0],
                provider_ids=(left.provider_id, right.provider_id),
                evidence_ids=(left.evidence_id, right.evidence_id),
            )
        )

    if diagnostics:
        return ReconciliationResult(
            reconciled_indices=(),
            blocking_errors=(
                GateError(
                    code="core_index_source_conflict",
                    module="market_indices",
                    message="核心指数双来源核对不一致",
                    evidence_ids=tuple(
                        record.evidence_id for record in records
                    ),
                ),
            ),
            diagnostics=tuple(diagnostics),
        )
    return ReconciliationResult(
        reconciled_indices=tuple(reconciled),
        blocking_errors=(),
        diagnostics=(),
    )


def _failed_result(code: str, message: str) -> ReconciliationResult:
    return ReconciliationResult(
        reconciled_indices=(),
        blocking_errors=(GateError(code=code, module="market_indices", message=message),),
        diagnostics=(),
    )


def _quantize(value: Decimal, decimal_places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _numeric_diagnostic(
    symbol: str,
    field: str,
    provider_ids: tuple[str, str],
    values: tuple[Decimal, Decimal],
) -> ReconciliationDiagnostic:
    return ReconciliationDiagnostic(
        symbol=symbol,
        field=field,
        provider_values=tuple(
            (provider_id, format(value, "f"))
            for provider_id, value in zip(provider_ids, values, strict=True)
        ),
    )
