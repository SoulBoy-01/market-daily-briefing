from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
import re
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from market_briefing.config import AppConfig, load_config
from market_briefing.audit import recover_orphaned_publication_directories
from market_briefing.domain import FeedbackEntry, RawSnapshot, Report, ReportType
from market_briefing.feedback import ALLOWED_FEEDBACK_TAGS, summarize_feedback, validate_feedback_entry
from market_briefing.labels import (
    confidence_label,
    coverage_status_label,
    fact_classification_label,
    feedback_tag_label,
    feedback_tags_label,
    module_label,
    report_type_label,
    section_label,
    source_type_label,
    status_label,
)
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import AuditIntegrityError, BriefingStore, RunAlreadyExistsError


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
REPORT_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_SOURCE_SCHEMES = {"fixture", "http", "https"}
CHINA_MARKET_TIMEZONE = timezone(timedelta(hours=8))


def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def create_app(config: AppConfig | None = None, store: BriefingStore | None = None) -> FastAPI:
    app_config = config or load_default_app_config()
    briefing_store = store or BriefingStore(app_config.database_path)
    briefing_store.initialize()
    recover_orphaned_publication_directories(
        raw_dir=app_config.raw_dir,
        reports_dir=app_config.reports_dir,
        diagnostics_dir=app_config.effective_diagnostics_dir,
        published_run_ids=briefing_store.published_run_ids(),
    )

    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.filters["safe_source_url"] = safe_source_url
    templates.env.filters["report_type_label"] = report_type_label
    templates.env.filters["fact_classification_label"] = fact_classification_label
    templates.env.filters["source_type_label"] = source_type_label
    templates.env.filters["confidence_label"] = confidence_label
    templates.env.filters["coverage_status_label"] = coverage_status_label
    templates.env.filters["status_label"] = status_label
    templates.env.filters["module_label"] = module_label
    templates.env.filters["section_label"] = section_label
    templates.env.filters["feedback_tag_label"] = feedback_tag_label
    templates.env.filters["feedback_tags_label"] = feedback_tags_label
    app = FastAPI(title="A股每日市场简报工作台")
    app.state.config = app_config
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/")
    def dashboard(request: Request):
        reports = briefing_store.list_reports()
        latest_report = reports[0] if reports else None
        review_report = _select_review_report(reports, latest_report)
        latest_feedback = (
            briefing_store.list_feedback(review_report.report_id) if review_report else []
        )
        latest_facts = (
            briefing_store.list_facts(review_report.run_id) if review_report else []
        )
        review_warnings = (
            briefing_store.list_run_warnings(review_report.run_id) if review_report else []
        )
        review_coverage = (
            briefing_store.list_module_coverage(review_report.run_id) if review_report else []
        )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "latest_report": latest_report,
                "review_report": review_report,
                "reports": reports,
                "latest_facts": latest_facts,
                "run_warnings": review_warnings,
                "module_coverage": review_coverage,
                "feedback_summary": summarize_feedback(latest_feedback),
                "report_types": list(ReportType),
                "default_report_date": _default_report_date(),
            },
        )

    @app.get("/runs/fixture")
    def run_fixture_form(request: Request):
        return templates.TemplateResponse(
            request,
            "run.html",
            {
                "report_types": list(ReportType),
                "default_report_date": _default_report_date(),
            },
        )

    @app.post("/runs/fixture")
    def run_fixture(
        run_id: Annotated[str, Form()],
        report_date: Annotated[str, Form()],
        report_type: Annotated[ReportType, Form()],
        fixture_path: Annotated[str, Form()],
    ):
        _validate_run_id(run_id)
        _validate_report_date(report_date)
        safe_fixture_path = _validate_fixture_path(fixture_path)
        try:
            result = run_fixture_pipeline(
                PipelineRequest(
                    run_id=run_id,
                    report_date=report_date,
                    report_type=report_type,
                    fixture_path=safe_fixture_path,
                ),
                config=app_config,
                store=briefing_store,
            )
        except RunAlreadyExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="运行 ID 已存在，请使用新的运行 ID",
            ) from exc
        if result.validation_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(result.validation_errors),
            )
        if result.report is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="pipeline completed without a report",
            )
        return RedirectResponse(
            url=f"/reports/{result.report.report_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get("/reports/{report_id}")
    def report_detail(request: Request, report_id: str):
        try:
            report = briefing_store.get_report(report_id)
            briefing_store.assert_report_integrity(report_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except AuditIntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="审计完整性校验失败",
            ) from exc

        facts = briefing_store.list_facts(report.run_id)
        snapshots = briefing_store.list_snapshots(report.run_id)
        feedback = briefing_store.list_feedback(report.report_id)
        run_warnings = briefing_store.list_run_warnings(report.run_id)
        module_coverage = briefing_store.list_module_coverage(report.run_id)
        return templates.TemplateResponse(
            request,
            "report.html",
            _report_template_context(
                report,
                facts,
                snapshots,
                feedback,
                run_warnings=run_warnings,
                module_coverage=module_coverage,
            ),
        )

    @app.post("/reports/{report_id}/feedback")
    def submit_feedback(
        request: Request,
        report_id: str,
        section_id: Annotated[str, Form()],
        score: Annotated[int, Form()],
        note: Annotated[str, Form()] = "",
        tags: Annotated[list[str] | None, Form()] = None,
    ):
        try:
            report = briefing_store.get_report(report_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

        section_ids = {section.section_id for section in report.sections}
        if section_id not in section_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="section_id 不属于当前简报",
            )

        entry = FeedbackEntry(
            feedback_id=f"feedback-{uuid4().hex}",
            report_id=report_id,
            section_id=section_id,
            score=score,
            tags=tuple(tags or []),
            note=note.strip(),
            created_at=datetime.now(timezone.utc),
        )
        errors = validate_feedback_entry(entry)
        if errors:
            facts = briefing_store.list_facts(report.run_id)
            snapshots = briefing_store.list_snapshots(report.run_id)
            feedback = briefing_store.list_feedback(report.report_id)
            run_warnings = briefing_store.list_run_warnings(report.run_id)
            module_coverage = briefing_store.list_module_coverage(report.run_id)
            return templates.TemplateResponse(
                request,
                "report.html",
                _report_template_context(
                    report,
                    facts,
                    snapshots,
                    feedback,
                    feedback_errors=errors,
                    feedback_form={
                        "section_id": section_id,
                        "score": score,
                        "tags": list(tags or []),
                        "note": entry.note,
                    },
                    run_warnings=run_warnings,
                    module_coverage=module_coverage,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        briefing_store.save_feedback(entry)
        return RedirectResponse(
            url=f"/reports/{report_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return app


def _select_review_report(reports: list[Report], fallback: Report | None) -> Report | None:
    for report in reports:
        if report.report_type == ReportType.AFTER_CLOSE:
            return report
    return fallback


def _snapshot_view(snapshot: RawSnapshot) -> dict[str, object]:
    raw_path = Path(snapshot.raw_path)
    content = ""
    if raw_path.exists():
        content = raw_path.read_text(encoding="utf-8")
    return {"snapshot": snapshot, "content": content}


def _report_template_context(
    report: Report,
    facts: list[object],
    snapshots: list[RawSnapshot],
    feedback: list[FeedbackEntry],
    feedback_errors: list[dict[str, str]] | None = None,
    feedback_form: dict[str, object] | None = None,
    run_warnings: list[object] | None = None,
    module_coverage: list[object] | None = None,
) -> dict[str, object]:
    return {
        "report": report,
        "facts": facts,
        "facts_by_id": {fact.fact_id: fact for fact in facts},
        "snapshots": [_snapshot_view(snapshot) for snapshot in snapshots],
        "feedback": feedback,
        "feedback_summary": summarize_feedback(feedback),
        "feedback_tags": sorted(ALLOWED_FEEDBACK_TAGS),
        "feedback_errors": feedback_errors or [],
        "feedback_form": feedback_form or {},
        "run_warnings": run_warnings or [],
        "module_coverage": module_coverage or [],
    }


def _validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id 只能包含字母、数字、下划线和连字符",
        )


def _validate_report_date(report_date: str) -> None:
    if not REPORT_DATE_PATTERN.fullmatch(report_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="report_date 必须使用 YYYY-MM-DD 格式",
        )


def _validate_fixture_path(fixture_path: str) -> Path:
    path = Path(fixture_path)
    windows_path = PureWindowsPath(fixture_path)
    if (
        path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in path.parts
        or ".." in windows_path.parts
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fixture_path 必须是不含路径穿越的相对路径",
        )

    project_root = PROJECT_ROOT.resolve()
    candidate = (project_root / path).resolve()
    if not candidate.is_relative_to(project_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fixture_path 必须位于项目根目录内",
        )

    if candidate.is_file():
        return candidate

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="fixture_path 不存在")


def safe_source_url(source_url: str) -> str | None:
    parsed = urlparse(source_url.strip())
    if parsed.scheme.lower() in SAFE_SOURCE_SCHEMES:
        return source_url.strip()
    return None


def load_default_app_config() -> AppConfig:
    config_path = default_config_path()
    config = load_config(config_path)
    project_root = config_path.parent.parent.resolve()
    return replace(
        config,
        database_path=_resolve_default_config_path(config.database_path, project_root),
        raw_dir=_resolve_default_config_path(config.raw_dir, project_root),
        staging_dir=_resolve_default_config_path(config.effective_staging_dir, project_root),
        diagnostics_dir=_resolve_default_config_path(
            config.effective_diagnostics_dir, project_root
        ),
        reports_dir=_resolve_default_config_path(config.reports_dir, project_root),
    )


def _resolve_default_config_path(path: Path, project_root: Path) -> Path:
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _default_report_date() -> str:
    return datetime.now(CHINA_MARKET_TIMEZONE).date().isoformat()


app = create_app()
