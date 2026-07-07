from market_briefing.labels import module_label, section_label


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
