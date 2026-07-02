from __future__ import annotations

from market_briefing.domain import FeedbackEntry


ALLOWED_FEEDBACK_TAGS = {
    "missing_key_point",
    "weak_source",
    "too_verbose",
    "too_much_opinion",
    "insufficient_risk",
    "unclear_citation",
}


def validate_feedback_entry(entry: FeedbackEntry) -> list[str]:
    errors: list[str] = []
    if entry.score < 1 or entry.score > 5:
        errors.append("score must be between 1 and 5")
    unknown_tags = [tag for tag in entry.tags if tag not in ALLOWED_FEEDBACK_TAGS]
    if unknown_tags:
        errors.append(f"unknown feedback tags: {','.join(unknown_tags)}")
    if len(entry.note) > 240:
        errors.append("note must be 240 characters or fewer")
    return errors


def summarize_feedback(entries: list[FeedbackEntry]) -> str:
    if not entries:
        return "No previous feedback."

    average = sum(entry.score for entry in entries) / len(entries)
    lines = [f"Average score: {average:.1f}"]
    lines.extend(entry.summary_line() for entry in entries)
    return "\n".join(lines)
