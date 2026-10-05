from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from market_briefing.audit import rebase_audit_path, run_directory
from market_briefing.collectors.base import CollectionResult
from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.collectors.official_sources import OfficialSourceCollector
from market_briefing.config import AppConfig
from market_briefing.domain import (
    AtomicFact,
    CandidateReviewStatus,
    FactClassification,
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
from market_briefing.audit import move_run_directory, verify_snapshot_hash
from market_briefing.reconciliation import reconcile_core_indices
from market_briefing.reporting import build_report, render_html, render_markdown
from market_briefing.sources import (
    SourceRegistry,
    SourceRegistryError,
    require_dual_sourced_symbols,
)
from market_briefing.storage import (
    BriefingStore,
    PublishedRecordExistsError,
    build_report_paths,
)
from market_briefing.validation import (
    validate_real_publishable_facts,
    validate_report_sections,
)


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

    # 快照按暂存区真实路径入账；发布时随目录原子搬迁统一 rebase 到 raw/。
    snapshots = [*collected.snapshots, *official.snapshots]

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

    # 采集阶段的产物（快照、警告、覆盖状态）对候选审核界面可见，
    # 因此此时就写入账本；发布阶段补齐事实与报告（ADR 0006 决策 2）。
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
):
    run = store.get_run(request.run_id)
    if run is None:
        raise KeyError(request.run_id)
    if run.status in (RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS):
        raise PublishedRecordExistsError(
            f"运行 {request.run_id} 已发布，不可重复发布"
        )
    pending = _pending_candidate_ids(store, request.run_id)
    if pending:
        raise RuntimeError(
            f"仍有待审核候选项（{', '.join(pending)}），请先完成审核再发布"
        )

    snapshots = store.list_snapshots(request.run_id)
    records = _index_records_from_snapshots(snapshots)
    if not records:
        raise RuntimeError("缺少核心指数原始快照，无法执行双来源核对，禁止发布")
    reconciliation = reconcile_core_indices(records)
    if not reconciliation.passed:
        codes = ", ".join(error.code for error in reconciliation.blocking_errors)
        raise RuntimeError(f"双来源核对未通过（{codes}），禁止发布")

    facts = _publication_facts(
        store=store,
        request=request,
        snapshots=snapshots,
        reconciled=reconciliation.reconciled_indices,
    )
    real_validation = validate_real_publishable_facts(facts)
    if not real_validation.ok:
        raise RuntimeError(
            "真实发布校验未通过：" + "；".join(real_validation.errors)
        )

    report = build_report(
        report_id=f"report-{request.run_id}",
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        facts=facts,
        markdown_path="",
        html_path="",
        fact_ledger_path="",
    )
    sections = validate_report_sections(list(report.sections), facts)
    if not sections.ok:
        raise RuntimeError("报告校验未通过：" + "；".join(sections.errors))

    paths = _write_real_report_artifacts(config=config, request=request, report=report, facts=facts)
    final_report = replace(
        report,
        markdown_path=str(paths.markdown_path),
        html_path=str(paths.html_path),
        fact_ledger_path=str(paths.fact_ledger_path),
    )

    moved = move_run_directory(
        config.effective_staging_dir,
        config.raw_dir,
        request.report_date,
        request.run_id,
    )
    if moved is None:
        raise RuntimeError(f"运行 {request.run_id} 没有产生暂存目录")
    staging_run_dir = run_directory(
        config.effective_staging_dir, request.report_date, request.run_id
    )
    destination_run_dir = run_directory(config.raw_dir, request.report_date, request.run_id)
    published_snapshots = [
        replace(
            snapshot,
            raw_path=rebase_audit_path(snapshot.raw_path, staging_run_dir, destination_run_dir),
        )
        for snapshot in snapshots
    ]
    published_facts = [
        replace(
            fact,
            raw_snapshot_path=rebase_audit_path(
                fact.raw_snapshot_path,
                run_directory(
                    config.effective_staging_dir, request.report_date, request.run_id
                ),
                run_directory(config.raw_dir, request.report_date, request.run_id),
            ),
        )
        for fact in facts
    ]
    final_paths = build_report_paths(
        reports_dir=config.reports_dir,
        report_date=request.report_date,
        report_type=request.report_type,
        run_id=request.run_id,
    )
    final_report = replace(
        report,
        markdown_path=str(final_paths.markdown_path),
        html_path=str(final_paths.html_path),
        fact_ledger_path=str(final_paths.fact_ledger_path),
    )
    if final_paths.report_dir.exists():
        raise FileExistsError(final_paths.report_dir)
    final_paths.report_dir.parent.mkdir(parents=True, exist_ok=True)
    paths.report_dir.rename(final_paths.report_dir)

    store.rebase_snapshot_paths(
        request.run_id,
        {snapshot.snapshot_id: snapshot.raw_path for snapshot in published_snapshots},
    )
    store.publish_run_bundle(
        snapshots=[],
        facts=published_facts,
        report=final_report,
        target_status=RunStatus.COMPLETED,
    )
    return final_report


def _index_records_from_snapshots(snapshots: list[RawSnapshot]) -> list[MarketIndexRecord]:
    records: list[MarketIndexRecord] = []
    for snapshot in snapshots:
        if snapshot.module != "market_indices":
            continue
        verify_snapshot_hash(Path(snapshot.raw_path), snapshot.content_sha256)
        rows = json.loads(Path(snapshot.raw_path).read_text(encoding="utf-8"))
        records.extend(
            MarketIndexRecord(
                provider_id=str(snapshot.metadata["provider_id"]),
                trade_date=date.fromisoformat(str(row["trade_date"])),
                symbol=str(row["symbol"]),
                close=Decimal(str(row["close"])),
                change_pct=Decimal(str(row["change_pct"])),
                evidence_id=snapshot.snapshot_id,
            )
            for row in rows
        )
    return records


def _publication_facts(
    *,
    store: BriefingStore,
    request: RealAfterCloseRequest,
    snapshots: list[RawSnapshot],
    reconciled: tuple,
) -> list[AtomicFact]:
    from market_briefing.review import build_fact_from_approved_candidate

    facts: list[AtomicFact] = []
    snapshot_by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    for candidate_id, approved_fact_id, excerpt in _approved_candidates(store, request.run_id):
        events = store.list_candidate_review_events(candidate_id)
        review_event = events[-1]
        candidate = store.get_candidate(candidate_id)
        snapshot = snapshot_by_id.get(candidate.snapshot_id)
        if snapshot is None:
            raise RuntimeError(f"已批准候选 {candidate_id} 的快照缺失，禁止发布")
        facts.append(
            build_fact_from_approved_candidate(
                candidate=candidate,
                review_event=review_event,
                snapshot=snapshot,
                report_date=request.report_date,
                report_type=request.report_type,
            )
        )
        facts[-1] = replace(facts[-1], fact_id=approved_fact_id)

    index_snapshot = next(
        (snapshot for snapshot in snapshots if snapshot.module == "market_indices"),
        None,
    )
    if index_snapshot is None:
        raise RuntimeError("缺少核心指数快照，禁止发布")
    for index in reconciled:
        facts.append(
            AtomicFact(
                fact_id=f"fact-{request.run_id}-index-{index.symbol}",
                run_id=request.run_id,
                report_date=request.report_date,
                report_type=request.report_type,
                module="market_indices",
                claim=(
                    f"{index.symbol} 收盘 {index.close}，"
                    f"较前一交易日 {index.change_pct}%"
                    f"（双来源核对一致：{'、'.join(index.provider_ids)}）。"
                ),
                classification=FactClassification.FACT,
                source_name="、".join(index.provider_ids),
                source_url=index_snapshot.source_url,
                source_type=index_snapshot.source_type,
                published_at=None,
                fetched_at=index_snapshot.fetched_at,
                confidence="high",
                raw_snapshot_path=index_snapshot.raw_path,
                source_snapshot_id=index_snapshot.snapshot_id,
                used_in_sections=["market_indices"],
            )
        )
    return facts


def _approved_candidates(store: BriefingStore, run_id: str) -> list[tuple[str, str, str]]:
    approved: list[tuple[str, str, str]] = []
    with store.connection() as connection:
        rows = connection.execute(
            """
            select candidates.candidate_id, events.approved_fact_id
            from evidence_candidates as candidates
            join candidate_review_events as events
              on events.candidate_id = candidates.candidate_id
            where candidates.run_id = ?
              and events.event_id = (
                select latest.event_id
                from candidate_review_events as latest
                where latest.candidate_id = candidates.candidate_id
                order by latest.event_id desc
                limit 1
              )
              and events.to_status = ?
            order by candidates.candidate_id
            """,
            (run_id, CandidateReviewStatus.APPROVED.value),
        ).fetchall()
    approved.extend((row["candidate_id"], row["approved_fact_id"], "") for row in rows)
    return approved


def _write_real_report_artifacts(*, config: AppConfig, request, report, facts):
    report_dir = (
        config.effective_staging_dir
        / "reports"
        / request.report_date
        / request.report_type.value
        / request.run_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = report_dir / "briefing.md"
    html_path = report_dir / "briefing.html"
    ledger_path = report_dir / "fact_ledger.json"
    markdown = render_markdown(report, facts)
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(render_html(markdown), encoding="utf-8")
    ledger_path.write_text(
        json.dumps([fact.to_record() for fact in facts], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return build_report_paths(
        reports_dir=config.effective_staging_dir / "reports",
        report_date=request.report_date,
        report_type=request.report_type,
        run_id=request.run_id,
    )


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
