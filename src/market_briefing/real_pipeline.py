from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from market_briefing.audit import rebase_audit_path, run_directory
from market_briefing.collectors.base import CollectionResult
from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.collectors.official_sources import OfficialSourceCollector
from market_briefing.config import AppConfig
from market_briefing.domain import (
    AtomicFact,
    MarketIndexRecord,
    ModuleCoverage,
    ModuleCoverageStatus,
    OfficialCheckStatus,
    RawSnapshot,
    ReportType,
    Run,
    RunStatus,
    RunWarning,
    SectorSnapshotRecord,
)
from market_briefing.gates import evaluate_after_close_gate
from market_briefing.reconciliation import reconcile_core_indices
from market_briefing.sources import (
    SourceRegistry,
    SourceRegistryError,
    require_dual_sourced_symbols,
)
from market_briefing.storage import BriefingStore


CORE_INDEX_SYMBOLS = ("000001.SH", "399001.SZ", "399006.SZ")


class RealModeDisabledError(RuntimeError):
    """真实模式未解锁：来源登记不满足 ADR 0001 的双来源硬门槛。"""


@dataclass(frozen=True)
class RealAfterCloseRequest:
    """真实盘后请求。刻意不携带 fixture_path：不存在 fixture 静默回退。"""

    run_id: str
    report_date: str
    report_type: ReportType

    def __post_init__(self) -> None:
        if self.report_type is not ReportType.AFTER_CLOSE:
            raise ValueError("real 模式只支持 after_close")


@dataclass(frozen=True)
class CollectResult:
    run_id: str
    status: RunStatus
    blocking_error_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()


def collect_real_after_close(
    *,
    request: RealAfterCloseRequest,
    config: AppConfig,
    store: BriefingStore,
    registry: SourceRegistry,
    market_clients: tuple[MarketDataCollector, ...],
    official_collector: OfficialSourceCollector | None,
) -> CollectResult:
    try:
        require_dual_sourced_symbols(registry, CORE_INDEX_SYMBOLS)
    except SourceRegistryError as exc:
        raise RealModeDisabledError(str(exc)) from exc

    enabled_modules = config.enabled_modules(request.report_type)
    run_directory(
        config.effective_staging_dir,
        request.report_date,
        request.run_id,
    )
    run = Run.create(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
    )
    store.create_run(run)
    store.transition_run(run.run_id, RunStatus.RUNNING)

    collected = _collect_market_data(
        request=request,
        config=config,
        market_clients=market_clients,
        enabled_modules=enabled_modules,
    )
    official = (
        official_collector.collect(
            run_id=request.run_id,
            report_date=request.report_date,
            report_type=request.report_type,
            enabled_modules=enabled_modules,
            raw_dir=config.effective_staging_dir,
        )
        if official_collector is not None
        else CollectionResult(snapshots=[], facts=[])
    )

    snapshots = [*collected.snapshots, *official.snapshots]
    staging_run_dir = run_directory(
        config.effective_staging_dir,
        request.report_date,
        request.run_id,
    )
    destination_run_dir = run_directory(
        config.raw_dir,
        request.report_date,
        request.run_id,
    )
    snapshots = [
        replace(
            snapshot,
            raw_path=rebase_audit_path(
                snapshot.raw_path, staging_run_dir, destination_run_dir
            ),
        )
        for snapshot in snapshots
    ]

    reconciliation = reconcile_core_indices(collected.market_index_records)
    gate = evaluate_after_close_gate(
        run_id=request.run_id,
        report_date=date.fromisoformat(request.report_date),
        core_indices=collected.market_index_records,
        market_temperature=None,
        sector_snapshot=collected.sector_snapshot,
        official_checks=tuple(check.status for check in official.official_checks),
        is_trading_day=True,
        evaluated_at=datetime.now(timezone.utc),
    )
    blocking = tuple(error.code for error in reconciliation.blocking_errors) + tuple(
        error.code for error in gate.blocking_errors
    )
    warnings = _merge_warnings(request.run_id, gate.warnings, official.official_checks)
    coverage = _module_coverage(request, collected, official)

    for snapshot in snapshots:
        store.save_snapshot(snapshot)
    for candidate in official.candidates:
        store.save_candidate(candidate)
    store.save_run_warnings(warnings)
    store.save_module_coverage(coverage)

    status = RunStatus.AWAITING_REVIEW if official.candidates else RunStatus.RUNNING
    if official.candidates:
        store.transition_run(
            request.run_id,
            RunStatus.AWAITING_REVIEW,
            warning_count=len(warnings),
            error_message="; ".join(blocking) if blocking else None,
        )
    return CollectResult(
        run_id=request.run_id,
        status=status,
        blocking_error_codes=blocking,
        warning_codes=tuple(warning.warning_id for warning in warnings),
        candidate_ids=tuple(candidate.candidate_id for candidate in official.candidates),
    )


def publish_real_after_close(
    *,
    request: RealAfterCloseRequest,
    config: AppConfig,
    store: BriefingStore,
) -> None:
    pending = _pending_candidate_ids(store, request.run_id)
    if pending:
        raise RuntimeError(
            f"仍有待审核候选项（{', '.join(pending)}），请先完成审核再发布"
        )
    raise NotImplementedError("发布动作将在候选审核接线后实现（ADR 0006 决策 2）")


@dataclass(frozen=True)
class _CollectedMarketData:
    snapshots: list[RawSnapshot]
    facts: list[AtomicFact]
    market_index_records: list[MarketIndexRecord]
    sector_snapshot: SectorSnapshotRecord | None


def _collect_market_data(
    *,
    request: RealAfterCloseRequest,
    config: AppConfig,
    market_clients: tuple[MarketDataCollector, ...],
    enabled_modules: list[str],
) -> _CollectedMarketData:
    snapshots: list[RawSnapshot] = []
    facts: list[AtomicFact] = []
    records: list[MarketIndexRecord] = []
    sector_snapshot = None
    for client in market_clients:
        result = client.collect(
            run_id=request.run_id,
            report_date=request.report_date,
            report_type=request.report_type,
            enabled_modules=enabled_modules,
            raw_dir=config.effective_staging_dir,
        )
        snapshots.extend(result.snapshots)
        facts.extend(result.facts)
        records.extend(result.market_index_records)
        if result.sector_snapshot is not None:
            sector_snapshot = result.sector_snapshot
    return _CollectedMarketData(
        snapshots=snapshots,
        facts=facts,
        market_index_records=records,
        sector_snapshot=sector_snapshot,
    )


def _merge_warnings(
    run_id: str,
    warnings: list[RunWarning],
    official_checks: tuple,
) -> list[RunWarning]:
    failed = [
        check for check in official_checks if check.status == OfficialCheckStatus.CHECK_FAILED
    ]
    extra = [
        RunWarning(
            warning_id=f"warning-{run_id}-official-check-failed-{check.source_name}",
            run_id=run_id,
            source_name=check.source_name,
            module=check.module,
            message="官方来源检查失败",
            detail=None,
            created_at=datetime.now(timezone.utc),
        )
        for check in failed
    ]
    return [*warnings, *extra]


def _module_coverage(
    request: RealAfterCloseRequest,
    collected: _CollectedMarketData,
    official: CollectionResult,
) -> list[ModuleCoverage]:
    recorded_at = datetime.now(timezone.utc)
    coverage = [
        ModuleCoverage(
            coverage_id=f"{request.run_id}-market_indices",
            run_id=request.run_id,
            module="market_indices",
            status=ModuleCoverageStatus.COVERED,
            source_name="双源核对",
            message="三个核心指数已完成双来源核对。",
            recorded_at=recorded_at,
        ),
        ModuleCoverage(
            coverage_id=f"{request.run_id}-market_temperature",
            run_id=request.run_id,
            module="market_temperature",
            status=ModuleCoverageStatus.UNSUPPORTED,
            source_name=None,
            message="市场温度采集器尚未接入（阶段三后续任务）。",
            recorded_at=recorded_at,
        ),
    ]
    if collected.sector_snapshot is None:
        coverage.append(
            ModuleCoverage(
                coverage_id=f"{request.run_id}-sector_moves",
                run_id=request.run_id,
                module="sector_moves",
                status=ModuleCoverageStatus.FAILED,
                source_name=None,
                message="板块数据缺失。",
                recorded_at=recorded_at,
            )
        )
    for check in official.official_checks:
        coverage.append(
            ModuleCoverage(
                coverage_id=f"{request.run_id}-{check.module}-{check.source_name}",
                run_id=request.run_id,
                module=check.module,
                status=_coverage_status(check.status),
                source_name=check.source_name,
                message=_coverage_message(check.status),
                recorded_at=recorded_at,
            )
        )
    return coverage


def _coverage_status(status: OfficialCheckStatus) -> ModuleCoverageStatus:
    if status == OfficialCheckStatus.CANDIDATES_FOUND:
        return ModuleCoverageStatus.PENDING_REVIEW
    if status == OfficialCheckStatus.CHECK_FAILED:
        return ModuleCoverageStatus.FAILED
    return ModuleCoverageStatus.NO_UPDATES


def _coverage_message(status: OfficialCheckStatus) -> str:
    if status == OfficialCheckStatus.CANDIDATES_FOUND:
        return "发现候选项，等待人工审核。"
    if status == OfficialCheckStatus.CHECK_FAILED:
        return "官方来源检查失败，覆盖不完整。"
    return "已检查，未发现新增事项。"


def _pending_candidate_ids(store: BriefingStore, run_id: str) -> tuple[str, ...]:
    pending = []
    with store.connection() as connection:
        rows = connection.execute(
            """
            select candidates.candidate_id
            from evidence_candidates as candidates
            where candidates.run_id = ?
              and (
                select events.to_status
                from candidate_review_events as events
                where events.candidate_id = candidates.candidate_id
                order by events.event_id desc
                limit 1
              ) = ?
            order by candidates.candidate_id
            """,
            (run_id, "pending"),
        ).fetchall()
    pending.extend(row["candidate_id"] for row in rows)
    return tuple(pending)
