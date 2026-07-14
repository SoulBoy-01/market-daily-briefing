from __future__ import annotations

from typing import Any

from market_briefing.domain import (
    FactClassification,
    ModuleCoverageStatus,
    ReportType,
    SourceType,
)


REPORT_TYPE_LABELS = {
    ReportType.AFTER_CLOSE.value: "收盘后简报",
    ReportType.PRE_OPEN_UPDATE.value: "盘前更新",
}

REPORT_TITLE_LABELS = {
    ReportType.AFTER_CLOSE.value: "A股盘后简报",
    ReportType.PRE_OPEN_UPDATE.value: "A股早盘补充",
}

FACT_CLASSIFICATION_LABELS = {
    FactClassification.FACT.value: "事实",
    FactClassification.OPINION.value: "观点",
    FactClassification.INFERENCE.value: "推测/归纳",
    FactClassification.UNVERIFIED.value: "待确认",
}

SOURCE_TYPE_LABELS = {
    SourceType.OFFICIAL.value: "官方",
    SourceType.EXCHANGE.value: "交易所",
    SourceType.MEDIA.value: "媒体",
    SourceType.DATA_API.value: "数据接口",
    SourceType.OTHER.value: "其他",
}

CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

STATUS_LABELS = {
    "ok": "正常",
    "created": "已创建",
    "running": "运行中",
    "completed": "已完成",
    "completed_with_warnings": "已完成，有警告",
    "failed": "失败",
}

COVERAGE_STATUS_LABELS = {
    ModuleCoverageStatus.COVERED.value: "已覆盖",
    ModuleCoverageStatus.NO_UPDATES.value: "已检查，无新增",
    ModuleCoverageStatus.PENDING_REVIEW.value: "待审核",
    ModuleCoverageStatus.FAILED.value: "检查失败",
    ModuleCoverageStatus.UNSUPPORTED.value: "暂未支持",
}

MODULE_LABELS = {
    "market_indices": "市场指数",
    "market_temperature": "市场温度",
    "sector_moves": "板块表现",
    "policy_regulation": "政策/监管",
    "major_news": "重大新闻",
    "risk_points": "风险点",
    "overnight_context": "隔夜环境",
    "policy_news_delta": "政策新闻变化",
    "today_watchpoints": "今日关注点",
}

SECTION_LABELS = {
    "market_indices": "指数表现",
    "market_temperature": "市场温度",
    "sector_moves": "板块表现",
    "policy_regulation": "政策/监管",
    "major_news": "重大新闻",
    "risk_points": "风险提示",
    "overnight_context": "隔夜环境",
    "policy_news_delta": "政策新闻变化",
    "today_watchpoints": "今日关注点",
    "one_sentence_conclusion": "今日一句话结论",
    "market_overview": "市场全貌",
    "sector_strength": "强弱板块",
    "fact_opinion_inference": "事实 / 观点 / 推测分栏",
    "next_watchlist": "下一轮观察清单",
    "previous_feedback": "上一轮反馈回执",
}

FEEDBACK_TAG_LABELS = {
    "missing_key_point": "缺少关键点",
    "weak_source": "来源偏弱",
    "too_verbose": "过于冗长",
    "too_much_opinion": "观点过多",
    "insufficient_risk": "风险提示不足",
    "unclear_citation": "引用不清",
}


def _label(value: Any, labels: dict[str, str]) -> str:
    key = getattr(value, "value", value)
    return labels.get(str(key), str(key))


def report_type_label(value: Any) -> str:
    return _label(value, REPORT_TYPE_LABELS)


def report_title_label(value: Any) -> str:
    return _label(value, REPORT_TITLE_LABELS)


def fact_classification_label(value: Any) -> str:
    return _label(value, FACT_CLASSIFICATION_LABELS)


def source_type_label(value: Any) -> str:
    return _label(value, SOURCE_TYPE_LABELS)


def confidence_label(value: Any) -> str:
    return _label(value, CONFIDENCE_LABELS)


def status_label(value: Any) -> str:
    return _label(value, STATUS_LABELS)


def coverage_status_label(value: Any) -> str:
    return _label(value, COVERAGE_STATUS_LABELS)


def module_label(value: Any) -> str:
    return _label(value, MODULE_LABELS)


def section_label(value: Any) -> str:
    key = getattr(value, "value", value)
    return SECTION_LABELS.get(str(key), module_label(value))


def feedback_tag_label(value: Any) -> str:
    return _label(value, FEEDBACK_TAG_LABELS)


def feedback_tags_label(values: Any) -> str:
    tags = list(values or [])
    if not tags:
        return "无"
    return "、".join(feedback_tag_label(tag) for tag in tags)
