from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from market_briefing.collectors.fixtures import FixtureCollector
from market_briefing.config import AppConfig, load_config
from market_briefing.domain import Report, ReportType, Run
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
    report: Report
    validation_errors: list[str]


def run_fixture_pipeline(
    request: PipelineRequest,
    config: AppConfig,
    store: BriefingStore,
) -> PipelineResult:
    enabled_modules = config.enabled_modules(request.report_type)
    run = Run.create(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
    )
    store.save_run(run)

    collection = FixtureCollector(request.fixture_path).collect(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
        raw_dir=config.raw_dir,
    )
    for snapshot in collection.snapshots:
        store.save_snapshot(snapshot)
    store.save_facts(collection.facts)

    paths = build_report_paths(
        reports_dir=config.reports_dir,
        report_date=request.report_date,
        report_type=request.report_type,
        run_id=request.run_id,
    )
    paths.report_dir.mkdir(parents=True, exist_ok=True)

    report = build_report(
        report_id=f"report-{request.run_id}",
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        facts=collection.facts,
        markdown_path=str(paths.markdown_path),
        html_path=str(paths.html_path),
        fact_ledger_path=str(paths.fact_ledger_path),
    )
    validation = validate_report_sections(report.sections, collection.facts)

    markdown = render_markdown(report, collection.facts)
    paths.markdown_path.write_text(markdown, encoding="utf-8")
    paths.html_path.write_text(render_html(markdown), encoding="utf-8")
    paths.fact_ledger_path.write_text(
        json.dumps(
            [fact.to_record() for fact in collection.facts],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    store.save_report(report)
    return PipelineResult(report=report, validation_errors=validation.errors)


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
    print(result.report.markdown_path)


if __name__ == "__main__":
    main()
