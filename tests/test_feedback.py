from datetime import datetime, timezone

from market_briefing.domain import FeedbackEntry
from market_briefing.feedback import summarize_feedback, validate_feedback_entry
from market_briefing.storage import BriefingStore


def test_validate_feedback_rejects_score_outside_one_to_five():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=6,
        tags=["insufficient_risk"],
        note="风险提示可以更具体。",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    assert validate_feedback_entry(entry) == ["score must be between 1 and 5"]


def test_summarize_feedback_returns_compact_next_run_context():
    entries = [
        FeedbackEntry(
            feedback_id="feedback-001",
            report_id="report-001",
            section_id="risk_points",
            score=4,
            tags=["insufficient_risk", "unclear_citation"],
            note="风险提示要引用更清楚。",
            created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
        ),
        FeedbackEntry(
            feedback_id="feedback-002",
            report_id="report-001",
            section_id="market_indices",
            score=5,
            tags=[],
            note="指数部分清楚。",
            created_at=datetime(2026, 7, 2, 9, 5, tzinfo=timezone.utc),
        ),
    ]

    summary = summarize_feedback(entries)

    assert "Average score: 4.5" in summary
    assert (
        "risk_points: score=4; tags=insufficient_risk,unclear_citation; note=风险提示要引用更清楚。"
        in summary
    )
    assert "market_indices: score=5; tags=; note=指数部分清楚。" in summary


def test_store_round_trips_feedback(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk"],
        note="风险提示要引用更清楚。",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    store.save_feedback(entry)
    loaded = store.list_feedback("report-001")

    assert loaded == [entry]
