from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from market_briefing.domain import (
    AtomicFact,
    CandidateReviewEvent,
    CandidateReviewStatus,
    EvidenceCandidate,
    FactClassification,
    FeedbackEntry,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunEvent,
    RunStatus,
    SourceType,
    can_transition_run,
)


def test_raw_snapshot_can_be_serialized():
    metadata = {"row_count": 3, "symbols": ["000001.SH"]}
    snapshot = RawSnapshot(
        snapshot_id="snapshot-001",
        run_id="run-001",
        module="market_indices",
        source_name="Fixture Market Data",
        source_url="fixture://market/indices",
        source_type=SourceType.DATA_API,
        fetched_at=datetime(2026, 7, 2, 15, 10, tzinfo=timezone.utc),
        content_type="application/json",
        raw_path="data/raw/2026-07-02/run-001/indices.json",
        content_sha256="a" * 64,
        provider_name="Fixture Market Data",
        license_ref="fixture:test-data",
        metadata=metadata,
    )
    metadata["row_count"] = 99
    metadata["symbols"].append("399001.SZ")

    payload = snapshot.to_record()

    assert payload["snapshot_id"] == "snapshot-001"
    assert payload["source_type"] == "data_api"
    assert payload["fetched_at"] == "2026-07-02T15:10:00+00:00"
    assert payload["content_sha256"] == "a" * 64
    assert payload["provider_name"] == "Fixture Market Data"
    assert payload["license_ref"] == "fixture:test-data"
    assert payload["metadata"] == {"row_count": 3, "symbols": ["000001.SH"]}
    assert isinstance(snapshot.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        snapshot.metadata["row_count"] = 4


def test_atomic_fact_can_be_serialized():
    derived_from_fact_ids = ["source-fact-001"]
    used_in_sections = ["market_indices"]
    fact = AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="The Shanghai Composite closed up 0.5%.",
        classification=FactClassification.FACT,
        source_name="Fixture Market Data",
        source_url="fixture://market/indices",
        source_type=SourceType.DATA_API,
        published_at=datetime(2026, 7, 2, 15, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 2, 15, 10, tzinfo=timezone.utc),
        confidence="high",
        raw_snapshot_path="data/raw/2026-07-02/run-001/indices.json",
        derived_from_fact_ids=derived_from_fact_ids,
        used_in_sections=used_in_sections,
    )
    derived_from_fact_ids.append("source-fact-002")
    used_in_sections.append("risk_points")

    payload = fact.to_record()

    assert payload["fact_id"] == "fact-001"
    assert payload["classification"] == "fact"
    assert payload["report_type"] == "after_close"
    assert payload["source_type"] == "data_api"
    assert payload["derived_from_fact_ids"] == ["source-fact-001"]
    assert payload["used_in_sections"] == ["market_indices"]
    assert fact.derived_from_fact_ids == ("source-fact-001",)
    with pytest.raises(AttributeError):
        fact.used_in_sections.append("risk_points")


def test_report_collects_all_fact_ids_from_sections():
    fact_ids = ["fact-001"]
    section = ReportSection(
        section_id="market_indices",
        title="Index performance",
        body="Shanghai Composite closed higher. [fact-001]",
        fact_ids=fact_ids,
        status="ok",
    )
    fact_ids.append("fact-002")
    sections = [section]
    report = Report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="A-share after-close briefing",
        sections=sections,
        markdown_path="reports/2026-07-02/after_close/briefing.md",
        html_path="reports/2026-07-02/after_close/briefing.html",
        fact_ledger_path="reports/2026-07-02/after_close/fact_ledger.json",
    )
    sections.append(
        ReportSection(
            section_id="risk_points",
            title="Risk points",
            body="No new fact.",
            fact_ids=["fact-003"],
            status="ok",
        )
    )

    assert report.all_fact_ids() == {"fact-001"}
    assert section.fact_ids == ("fact-001",)
    assert report.sections == (section,)
    with pytest.raises(AttributeError):
        report.sections.append(section)


def test_feedback_entry_summarizes_tags_and_note():
    tags = ["insufficient_risk", "unclear_citation"]
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=tags,
        note="Risk points should cite facts more clearly.",
        created_at=datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc),
    )
    tags.append("too_long")

    assert (
        entry.summary_line()
        == "risk_points: score=4; tags=insufficient_risk,unclear_citation; note=Risk points should cite facts more clearly."
    )
    assert entry.tags == ("insufficient_risk", "unclear_citation")
    with pytest.raises(AttributeError):
        entry.tags.append("unclear_citation")


def test_run_defaults_to_created_status_and_tracks_modules():
    enabled_modules = ["overnight_context", "today_watchpoints"]
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.PRE_OPEN_UPDATE,
        enabled_modules=enabled_modules,
    )
    enabled_modules.append("market_indices")

    assert run.status == RunStatus.CREATED
    assert run.enabled_modules == ("overnight_context", "today_watchpoints")
    with pytest.raises(AttributeError):
        run.enabled_modules.append("market_indices")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.CREATED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.AWAITING_REVIEW),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.COMPLETED_WITH_WARNINGS),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.AWAITING_REVIEW, RunStatus.COMPLETED),
        (RunStatus.AWAITING_REVIEW, RunStatus.COMPLETED_WITH_WARNINGS),
        (RunStatus.AWAITING_REVIEW, RunStatus.FAILED),
    ],
)
def test_run_state_machine_allows_only_declared_forward_transitions(current, target):
    assert can_transition_run(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.CREATED, RunStatus.COMPLETED),
        (RunStatus.RUNNING, RunStatus.CREATED),
        (RunStatus.AWAITING_REVIEW, RunStatus.RUNNING),
        (RunStatus.COMPLETED, RunStatus.RUNNING),
        (RunStatus.COMPLETED_WITH_WARNINGS, RunStatus.FAILED),
        (RunStatus.FAILED, RunStatus.CREATED),
    ],
)
def test_run_state_machine_rejects_skips_backtracking_and_terminal_changes(current, target):
    assert not can_transition_run(current, target)


def test_run_event_is_immutable():
    event = RunEvent(
        event_id=1,
        run_id="run-001",
        from_status=None,
        to_status=RunStatus.CREATED,
        created_at=datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(AttributeError):
        event.to_status = RunStatus.RUNNING


def test_evidence_candidate_and_review_event_are_immutable_audit_records():
    candidate = EvidenceCandidate(
        candidate_id="candidate-001",
        run_id="run-001",
        snapshot_id="snapshot-001",
        module="policy_regulation",
        title="交易所发布一项规则说明",
        detail_url="https://example.test/rule-001",
        published_at=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
        excerpt="规则说明自发布之日起施行。",
        suggested_classification=FactClassification.FACT,
        created_at=datetime(2026, 7, 2, 8, 5, tzinfo=timezone.utc),
    )
    event = CandidateReviewEvent(
        event_id=2,
        candidate_id=candidate.candidate_id,
        from_status=CandidateReviewStatus.PENDING,
        to_status=CandidateReviewStatus.APPROVED,
        reviewed_at=datetime(2026, 7, 2, 8, 10, tzinfo=timezone.utc),
        reviewer_id="local-maintainer",
        note="已与详情页原文核对。",
        approved_fact_id="fact-candidate-001",
    )

    assert candidate.to_record()["suggested_classification"] == "fact"
    assert event.to_status == CandidateReviewStatus.APPROVED
    with pytest.raises(AttributeError):
        candidate.title = "被覆盖的标题"
    with pytest.raises(AttributeError):
        event.note = "被覆盖的审核备注"
