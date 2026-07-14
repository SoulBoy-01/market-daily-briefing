from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from market_briefing.domain import (
    MarketIndexRecord,
    MarketTemperatureRecord,
    OfficialCheckStatus,
    RunWarning,
    SectorSnapshotRecord,
)


CORE_INDEX_SYMBOLS = ("000001.SH", "399001.SZ", "399006.SZ")


@dataclass(frozen=True)
class GateError:
    code: str
    module: str
    message: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AfterCloseGateResult:
    blocking_errors: tuple[GateError, ...]
    warnings: tuple[RunWarning, ...]

    @property
    def publishable(self) -> bool:
        return not self.blocking_errors


def evaluate_after_close_gate(
    *,
    run_id: str,
    report_date: date,
    core_indices: list[MarketIndexRecord],
    market_temperature: MarketTemperatureRecord | None,
    sector_snapshot: SectorSnapshotRecord | None,
    official_checks: tuple[OfficialCheckStatus, ...],
    is_trading_day: bool,
    evaluated_at: datetime,
) -> AfterCloseGateResult:
    if not is_trading_day:
        return AfterCloseGateResult(
            blocking_errors=(
                GateError(
                    code="not_trading_day",
                    module="market_indices",
                    message="报告日期不是数据源确认的交易日",
                ),
            ),
            warnings=(),
        )

    errors = _core_index_errors(core_indices, report_date)
    warnings = [
        *_market_temperature_warnings(
            run_id,
            report_date,
            market_temperature,
            evaluated_at,
        ),
        *_sector_warnings(run_id, report_date, sector_snapshot, evaluated_at),
    ]
    if OfficialCheckStatus.CANDIDATES_FOUND in official_checks:
        errors.append(
            GateError(
                code="pending_official_review",
                module="policy_regulation",
                message="官方候选项尚未完成审核",
            )
        )
    if OfficialCheckStatus.CHECK_FAILED in official_checks:
        warnings.append(
            RunWarning(
                warning_id=f"warning-{run_id}-official-check-failed",
                run_id=run_id,
                source_name="官方来源",
                module="policy_regulation",
                message="官方来源检查失败",
                detail=None,
                created_at=evaluated_at,
            )
        )
    return AfterCloseGateResult(
        blocking_errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _core_index_errors(
    records: list[MarketIndexRecord],
    report_date: date,
) -> list[GateError]:
    errors: list[GateError] = []
    present_symbols = {record.symbol for record in records}
    missing_symbols = [symbol for symbol in CORE_INDEX_SYMBOLS if symbol not in present_symbols]
    if missing_symbols:
        errors.append(
            GateError(
                code="core_index_missing",
                module="market_indices",
                message=f"核心指数缺失：{', '.join(missing_symbols)}",
            )
        )

    record_keys = [(record.provider_id, record.symbol) for record in records]
    if len(record_keys) != len(set(record_keys)):
        errors.append(
            GateError(
                code="core_index_duplicate",
                module="market_indices",
                message="核心指数存在重复来源记录",
            )
        )
    if any(record.trade_date != report_date for record in records):
        errors.append(
            GateError(
                code="core_index_stale",
                module="market_indices",
                message="核心指数交易日与报告日期不一致",
                evidence_ids=tuple(
                    record.evidence_id for record in records if record.trade_date != report_date
                ),
            )
        )
    if any(not _valid_index_values(record) for record in records):
        errors.append(
            GateError(
                code="core_index_invalid_value",
                module="market_indices",
                message="核心指数包含非法数值",
                evidence_ids=tuple(
                    record.evidence_id for record in records if not _valid_index_values(record)
                ),
            )
        )
    return errors


def _valid_index_values(record: MarketIndexRecord) -> bool:
    return (
        isinstance(record.close, Decimal)
        and isinstance(record.change_pct, Decimal)
        and record.close.is_finite()
        and record.change_pct.is_finite()
        and record.close > 0
    )


def _market_temperature_warnings(
    run_id: str,
    report_date: date,
    record: MarketTemperatureRecord | None,
    evaluated_at: datetime,
) -> list[RunWarning]:
    if record is None:
        return [
            _warning(
                run_id,
                "market-temperature-missing",
                "market_temperature",
                "市场温度数据缺失",
                "市场温度来源",
                evaluated_at,
            )
        ]
    if record.trade_date != report_date:
        return [
            _warning(
                run_id,
                "market-temperature-stale",
                "market_temperature",
                "市场温度数据不是报告日期",
                record.provider_id,
                evaluated_at,
            )
        ]
    return []


def _sector_warnings(
    run_id: str,
    report_date: date,
    record: SectorSnapshotRecord | None,
    evaluated_at: datetime,
) -> list[RunWarning]:
    if record is None:
        return [
            _warning(
                run_id,
                "sector-missing",
                "sector_moves",
                "板块数据缺失",
                "板块来源",
                evaluated_at,
            )
        ]
    if record.trade_date != report_date:
        return [
            _warning(
                run_id,
                "sector-stale",
                "sector_moves",
                "板块数据不是报告日期",
                record.provider_id,
                evaluated_at,
            )
        ]
    return []


def _warning(
    run_id: str,
    code: str,
    module: str,
    message: str,
    source_name: str,
    created_at: datetime,
) -> RunWarning:
    return RunWarning(
        warning_id=f"warning-{run_id}-{code}",
        run_id=run_id,
        source_name=source_name,
        module=module,
        message=message,
        detail=None,
        created_at=created_at,
    )
