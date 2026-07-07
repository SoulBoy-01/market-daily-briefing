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

    assert validate_feedback_entry(entry) == [
        {"field": "score", "code": "out_of_range", "message": "评分必须在 1 到 5 之间"}
    ]


def test_validate_feedback_rejects_unknown_tag_with_exact_error():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["unexpected_tag"],
        note="Needs sharper risk context.",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    assert validate_feedback_entry(entry) == [
        {"field": "tags", "code": "unknown", "message": "反馈标签无效：unexpected_tag"}
    ]


def test_validate_feedback_rejects_note_longer_than_240_characters():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk"],
        note="x" * 241,
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    assert validate_feedback_entry(entry) == [
        {"field": "note", "code": "too_long", "message": "备注不能超过 240 个字"}
    ]


def test_summarize_feedback_returns_exact_empty_context():
    assert summarize_feedback([]) == "暂无历史反馈。"


def test_summarize_feedback_accepts_contextual_empty_message():
    assert (
        summarize_feedback([], empty_message="暂无历史反馈。上一轮简报未收到反馈提交。")
        == "暂无历史反馈。上一轮简报未收到反馈提交。"
    )


def test_summarize_feedback_uses_section_label_for_beginner_sections():
    entries = [
        FeedbackEntry(
            feedback_id="feedback-001",
            report_id="report-001",
            section_id="one_sentence_conclusion",
            score=4,
            tags=[],
            note="标题摘要清楚。",
            created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
        )
    ]

    summary = summarize_feedback(entries)

    assert "今日一句话结论：评分=4" in summary
    assert "one_sentence_conclusion" not in summary


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

    assert "平均评分：4.5" in summary
    assert (
        "风险提示：评分=4；标签=风险提示不足、引用不清；备注=风险提示要引用更清楚。"
        in summary
    )
    assert "指数表现：评分=5；标签=无；备注=指数部分清楚。" in summary


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


def test_list_feedback_orders_by_created_at_then_feedback_id(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    later_entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=3,
        tags=["insufficient_risk"],
        note="Later feedback.",
        created_at=datetime(2026, 7, 2, 9, 5, tzinfo=timezone.utc),
    )
    tie_second = FeedbackEntry(
        feedback_id="feedback-003",
        report_id="report-001",
        section_id="market_indices",
        score=5,
        tags=[],
        note="Same timestamp, higher id.",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )
    tie_first = FeedbackEntry(
        feedback_id="feedback-002",
        report_id="report-001",
        section_id="market_indices",
        score=4,
        tags=["unclear_citation"],
        note="Same timestamp, lower id.",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    store.save_feedback(later_entry)
    store.save_feedback(tie_second)
    store.save_feedback(tie_first)

    assert store.list_feedback("report-001") == [tie_first, tie_second, later_entry]
