from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from market_briefing.audit import (
    move_run_directory,
    rebase_audit_path,
    recover_orphaned_publication_directories,
    run_directory,
)
from market_briefing.collectors.fixtures import FixtureCollector
from market_briefing.config import AppConfig, load_config
from market_briefing.domain import AtomicFact, Report, ReportType, Run, RunStatus
from market_briefing.feedback import (
    FIRST_RUN_EMPTY_FEEDBACK_SUMMARY,
    PREVIOUS_REPORT_EMPTY_FEEDBACK_SUMMARY,
    summarize_feedback,
)
from market_briefing.reporting import build_report, render_html, render_markdown
from market_briefing.storage import BriefingStore, build_report_paths
from market_briefing.validation import validate_report_sections


@dataclass(frozen=True)
class PipelineRequest:
    run_id: str
    report_date: str
    report_type: ReportType
    fixture_path: Path


@dataclass(frozen=True)
class PipelineResult:
    """
    report is set only when validation_errors is empty and the pipeline succeeded.
    If validation failed before files were written, report is None and run is FAILED.
    """

    report: Report | None
    validation_errors: list[str]


def run_fixture_pipeline(
    request: PipelineRequest,
    config: AppConfig,
    store: BriefingStore,
) -> PipelineResult:
    run_directory(
        config.effective_staging_dir,
        request.report_date,
        request.run_id,
    )
    enabled_modules = config.enabled_modules(request.report_type)
    run = Run.create(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
    )
    store.create_run(run)
    recover_orphaned_publication_directories(
        raw_dir=config.raw_dir,
        reports_dir=config.reports_dir,
        diagnostics_dir=config.effective_diagnostics_dir,
        published_run_locations=store.published_run_locations(),
    )
    store.transition_run(run.run_id, RunStatus.RUNNING)

    try:
        collection = FixtureCollector(request.fixture_path).collect(
            run_id=request.run_id,
            report_date=request.report_date,
            report_type=request.report_type,
            enabled_modules=enabled_modules,
            raw_dir=config.effective_staging_dir,
        )
    except Exception as exc:
        move_run_directory(
            config.effective_staging_dir,
            config.effective_diagnostics_dir,
            request.report_date,
            request.run_id,
        )
        store.transition_run(
            run.run_id,
            RunStatus.FAILED,
            error_message=str(exc),
        )
        raise
    facts = _scope_facts_to_run(collection.facts, request.run_id)

    paths = build_report_paths(
        reports_dir=config.reports_dir,
        report_date=request.report_date,
        report_type=request.report_type,
        run_id=request.run_id,
    )
    previous_feedback_summary = _load_previous_feedback(
        store,
        report_type=request.report_type,
        report_date=request.report_date,
    )

    report = build_report(
        report_id=f"report-{request.run_id}",
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        facts=facts,
        markdown_path=str(paths.markdown_path),
        html_path=str(paths.html_path),
        fact_ledger_path=str(paths.fact_ledger_path),
        previous_feedback_summary=previous_feedback_summary,
    )
    validation = validate_report_sections(report.sections, facts)

    if not validation.ok:
        move_run_directory(
            config.effective_staging_dir,
            config.effective_diagnostics_dir,
            request.report_date,
            request.run_id,
        )
        store.transition_run(
            run.run_id,
            RunStatus.FAILED,
            warning_count=len(validation.errors),
        )
        return PipelineResult(report=None, validation_errors=validation.errors)

    source_run_dir = run_directory(
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
                snapshot.raw_path,
                source_run_dir,
                destination_run_dir,
            ),
        )
        for snapshot in collection.snapshots
    ]
    facts = [
        replace(
            fact,
            raw_snapshot_path=rebase_audit_path(
                fact.raw_snapshot_path,
                source_run_dir,
                destination_run_dir,
            ),
        )
        for fact in facts
    ]

    staged_paths = build_report_paths(
        reports_dir=config.effective_staging_dir / "reports",
        report_date=request.report_date,
        report_type=request.report_type,
        run_id=request.run_id,
    )
    try:
        staged_paths.report_dir.mkdir(parents=True, exist_ok=False)
        markdown = render_markdown(report, facts)
        staged_paths.markdown_path.write_text(markdown, encoding="utf-8")
        staged_paths.html_path.write_text(render_html(markdown), encoding="utf-8")
        staged_paths.fact_ledger_path.write_text(
            json.dumps(
                [fact.to_record() for fact in facts],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        moved = move_run_directory(
            config.effective_staging_dir,
            config.raw_dir,
            request.report_date,
            request.run_id,
        )
        if moved is None:
            raise RuntimeError(f"run {request.run_id} produced no staging directory")
        if paths.report_dir.exists():
            raise FileExistsError(paths.report_dir)
        paths.report_dir.parent.mkdir(parents=True, exist_ok=True)
        staged_paths.report_dir.rename(paths.report_dir)
        store.publish_run_bundle(
            snapshots=snapshots,
            facts=facts,
            report=report,
            target_status=RunStatus.COMPLETED,
            warning_count=0,
        )
    except Exception as exc:
        _recover_failed_publication(
            config=config,
            store=store,
            request=request,
            staged_report_dir=staged_paths.report_dir,
        )
        current_run = store.get_run(run.run_id)
        if current_run is not None and current_run.status == RunStatus.RUNNING:
            store.transition_run(
                run.run_id,
                RunStatus.FAILED,
                error_message=str(exc),
            )
        raise
    return PipelineResult(report=report, validation_errors=validation.errors)


def _recover_failed_publication(
    *,
    config: AppConfig,
    store: BriefingStore,
    request: PipelineRequest,
    staged_report_dir: Path,
) -> None:
    recover_orphaned_publication_directories(
        raw_dir=config.raw_dir,
        reports_dir=config.reports_dir,
        diagnostics_dir=config.effective_diagnostics_dir,
        published_run_locations=store.published_run_locations(),
    )
    diagnostics_run_dir = run_directory(
        config.effective_diagnostics_dir,
        request.report_date,
        request.run_id,
    )
    staged_raw_dir = run_directory(
        config.effective_staging_dir,
        request.report_date,
        request.run_id,
    )
    for source, label in (
        (staged_raw_dir, "failed-staging-raw"),
        (staged_report_dir, f"failed-staging-report-{request.report_type.value}"),
    ):
        if not source.exists():
            continue
        destination = diagnostics_run_dir / label
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)


def _scope_facts_to_run(facts: list[AtomicFact], run_id: str) -> list[AtomicFact]:
    fact_id_map = {fact.fact_id: f"{fact.fact_id}:{run_id}" for fact in facts}
    return [
        replace(
            fact,
            fact_id=fact_id_map[fact.fact_id],
            derived_from_fact_ids=tuple(
                fact_id_map.get(fact_id, fact_id) for fact_id in fact.derived_from_fact_ids
            ),
        )
        for fact in facts
    ]


def _load_previous_feedback(
    store: BriefingStore,
    report_type: ReportType,
    report_date: str,
) -> str:
    for report in store.list_reports():
        # B2: same-day reruns are not prior rounds; only earlier report dates count.
        if report.report_type != report_type or report.report_date >= report_date:
            continue
        return summarize_feedback(
            store.list_feedback(report.report_id),
            empty_message=PREVIOUS_REPORT_EMPTY_FEEDBACK_SUMMARY,
        )
    return summarize_feedback([], empty_message=FIRST_RUN_EMPTY_FEEDBACK_SUMMARY)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the market briefing fixture pipeline.")
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument(
        "--report-type",
        choices=[report_type.value for report_type in ReportType],
        required=True,
    )
    parser.add_argument("--fixture-path", type=Path, required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    store = BriefingStore(config.database_path)
    store.initialize()
    result = run_fixture_pipeline(
        PipelineRequest(
            run_id=args.run_id,
            report_date=args.report_date,
            report_type=ReportType(args.report_type),
            fixture_path=args.fixture_path,
        ),
        config=config,
        store=store,
    )
    if result.validation_errors:
        for error in result.validation_errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    if result.report is None:
        raise RuntimeError("pipeline completed without a report")
    print(result.report.markdown_path)


if __name__ == "__main__":
    main()
