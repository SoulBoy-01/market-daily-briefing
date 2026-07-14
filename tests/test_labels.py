import pytest

from market_briefing.domain import ModuleCoverageStatus
from market_briefing.labels import coverage_status_label, module_label, section_label


def test_section_label_names_beginner_report_sections():
    assert section_label("one_sentence_conclusion") == "今日一句话结论"
    assert section_label("previous_feedback") == "上一轮反馈回执"


def test_section_label_uses_section_titles_before_unknown_fallback():
    assert section_label("market_indices") == "指数表现"
    assert section_label("risk_points") == "风险提示"
    assert section_label("unknown_module") == "unknown_module"


def test_module_label_keeps_module_scope():
    assert module_label("market_indices") == "市场指数"
    assert module_label("risk_points") == "风险点"
    assert module_label("one_sentence_conclusion") == "one_sentence_conclusion"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ModuleCoverageStatus.COVERED, "已覆盖"),
        (ModuleCoverageStatus.NO_UPDATES, "已检查，无新增"),
        (ModuleCoverageStatus.PENDING_REVIEW, "待审核"),
        (ModuleCoverageStatus.FAILED, "检查失败"),
        (ModuleCoverageStatus.UNSUPPORTED, "暂未支持"),
    ],
)
def test_coverage_status_labels_are_user_facing_chinese(status, expected):
    assert coverage_status_label(status) == expected
