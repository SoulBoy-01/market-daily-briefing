from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from market_briefing.config import AppConfig, load_config
from market_briefing.domain import FeedbackEntry, RawSnapshot, ReportType
from market_briefing.feedback import ALLOWED_FEEDBACK_TAGS, summarize_feedback, validate_feedback_entry
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = Path("configs/default.yaml")


def create_app(config: AppConfig | None = None, store: BriefingStore | None = None) -> FastAPI:
    app_config = config or load_config(DEFAULT_CONFIG_PATH)
    briefing_store = store or BriefingStore(app_config.database_path)
    briefing_store.initialize()

    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app = FastAPI(title="Market Briefing Loop Dashboard")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/")
    def dashboard(request: Request):
        latest_report = briefing_store.latest_report()
        reports = briefing_store.list_reports()
        latest_feedback = (
            briefing_store.list_feedback(latest_report.report_id) if latest_report else []
        )
        latest_facts = (
            briefing_store.list_facts(latest_report.run_id) if latest_report else []
        )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "latest_report": latest_report,
                "reports": reports,
                "latest_facts": latest_facts,
                "feedback_summary": summarize_feedback(latest_feedback),
                "report_types": list(ReportType),
            },
        )

    @app.get("/runs/fixture")
    def run_fixture_form(request: Request):
        return templates.TemplateResponse(
            request,
            "run.html",
            {"report_types": list(ReportType)},
        )

    @app.post("/runs/fixture")
    def run_fixture(
        run_id: Annotated[str, Form()],
        report_date: Annotated[str, Form()],
        report_type: Annotated[ReportType, Form()],
        fixture_path: Annotated[str, Form()],
    ):
        result = run_fixture_pipeline(
            PipelineRequest(
                run_id=run_id,
                report_date=report_date,
                report_type=report_type,
                fixture_path=Path(fixture_path),
            ),
            config=app_config,
            store=briefing_store,
        )
        if result.validation_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(result.validation_errors),
            )
        return RedirectResponse(
            url=f"/reports/{result.report.report_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    @app.get("/reports/{report_id}")
    def report_detail(request: Request, report_id: str):
        try:
            report = briefing_store.get_report(report_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

        facts = briefing_store.list_facts(report.run_id)
        snapshots = briefing_store.list_snapshots(report.run_id)
        feedback = briefing_store.list_feedback(report.report_id)
        return templates.TemplateResponse(
            request,
            "report.html",
            {
                "report": report,
                "facts": facts,
                "facts_by_id": {fact.fact_id: fact for fact in facts},
                "snapshots": [_snapshot_view(snapshot) for snapshot in snapshots],
                "feedback": feedback,
                "feedback_summary": summarize_feedback(feedback),
                "feedback_tags": sorted(ALLOWED_FEEDBACK_TAGS),
            },
        )

    @app.post("/reports/{report_id}/feedback")
    def submit_feedback(
        report_id: str,
        section_id: Annotated[str, Form()],
        score: Annotated[int, Form()],
        note: Annotated[str, Form()] = "",
        tags: Annotated[list[str] | None, Form()] = None,
    ):
        try:
            briefing_store.get_report(report_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(errors),
            )
        briefing_store.save_feedback(entry)
        return RedirectResponse(
            url=f"/reports/{report_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return app


def _snapshot_view(snapshot: RawSnapshot) -> dict[str, object]:
    raw_path = Path(snapshot.raw_path)
    content = ""
    if raw_path.exists():
        content = raw_path.read_text(encoding="utf-8")
    return {"snapshot": snapshot, "content": content}


app = create_app()
