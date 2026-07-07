from __future__ import annotations

from market_briefing.domain import FeedbackEntry
from market_briefing.labels import FEEDBACK_TAG_LABELS, feedback_tags_label, section_label


ALLOWED_FEEDBACK_TAGS = set(FEEDBACK_TAG_LABELS)


def validate_feedback_entry(entry: FeedbackEntry) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if entry.score < 1 or entry.score > 5:
        errors.append(
            {
                "field": "score",
                "code": "out_of_range",
                "message": "评分必须在 1 到 5 之间",
            }
        )
    unknown_tags = [tag for tag in entry.tags if tag not in ALLOWED_FEEDBACK_TAGS]
    if unknown_tags:
        errors.append(
            {
                "field": "tags",
                "code": "unknown",
                "message": f"反馈标签无效：{','.join(unknown_tags)}",
            }
        )
    if len(entry.note) > 240:
        errors.append(
            {
                "field": "note",
                "code": "too_long",
                "message": "备注不能超过 240 个字",
            }
        )
    return errors


def summarize_feedback(entries: list[FeedbackEntry]) -> str:
    if not entries:
        return "暂无历史反馈。"

    average = sum(entry.score for entry in entries) / len(entries)
    lines = [f"平均评分：{average:.1f}"]
    lines.extend(
        (
            f"{section_label(entry.section_id)}：评分={entry.score}；"
            f"标签={feedback_tags_label(entry.tags)}；备注={entry.note}"
        )
        for entry in entries
    )
    return "\n".join(lines)
