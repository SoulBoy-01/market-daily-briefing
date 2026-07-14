from dataclasses import replace
from datetime import datetime, timezone

import pytest

from market_briefing.domain import (
    CandidateReviewEvent,
    CandidateReviewStatus,
    EvidenceCandidate,
    FactClassification,
    RawSnapshot,
    ReportType,
    SourceType,
)
from market_briefing.review import (
    CandidateNotApprovedError,
    CandidateSnapshotMismatchError,
    UnpublishableCandidateError,
    build_fact_from_approved_candidate,
)


def _candidate() -> EvidenceCandidate:
    return EvidenceCandidate(
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


def _snapshot() -> RawSnapshot:
    return RawSnapshot(
        snapshot_id="snapshot-001",
        run_id="run-001",
        module="policy_regulation",
        source_name="示例交易所",
        source_url="https://example.test/rule-001",
        source_type=SourceType.EXCHANGE,
        fetched_at=datetime(2026, 7, 2, 8, 5, tzinfo=timezone.utc),
        content_type="text/html",
        raw_path="raw/2026-07-02/run-001/rule-001.html",
        content_sha256="a" * 64,
        provider_name="示例交易所",
    )


def _review(status: CandidateReviewStatus) -> CandidateReviewEvent:
    return CandidateReviewEvent(
        event_id=2,
        candidate_id="candidate-001",
        from_status=CandidateReviewStatus.PENDING,
        to_status=status,
        reviewed_at=datetime(2026, 7, 2, 8, 10, tzinfo=timezone.utc),
        reviewer_id="local-maintainer",
        note="已核对详情页。",
        approved_fact_id=("fact-candidate-001" if status == CandidateReviewStatus.APPROVED else None),
    )


def test_approved_candidate_builds_fact_with_candidate_and_snapshot_links():
    fact = build_fact_from_approved_candidate(
        candidate=_candidate(),
        review_event=_review(CandidateReviewStatus.APPROVED),
        snapshot=_snapshot(),
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
    )

    assert fact.fact_id == "fact-candidate-001"
    assert fact.claim == "规则说明自发布之日起施行。"
    assert fact.classification == FactClassification.FACT
    assert fact.source_candidate_id == "candidate-001"
    assert fact.source_snapshot_id == "snapshot-001"
    assert fact.raw_snapshot_path == _snapshot().raw_path


def test_rejected_candidate_cannot_build_published_fact():
    with pytest.raises(CandidateNotApprovedError):
        build_fact_from_approved_candidate(
            candidate=_candidate(),
            review_event=_review(CandidateReviewStatus.REJECTED),
            snapshot=_snapshot(),
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
        )


def test_candidate_must_match_review_event_and_snapshot():
    with pytest.raises(CandidateSnapshotMismatchError):
        build_fact_from_approved_candidate(
            candidate=_candidate(),
            review_event=_review(CandidateReviewStatus.APPROVED),
            snapshot=replace(_snapshot(), run_id="other-run"),
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
        )


def test_unverified_candidate_cannot_build_published_fact():
    with pytest.raises(UnpublishableCandidateError):
        build_fact_from_approved_candidate(
            candidate=replace(
                _candidate(),
                suggested_classification=FactClassification.UNVERIFIED,
            ),
            review_event=_review(CandidateReviewStatus.APPROVED),
            snapshot=_snapshot(),
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
        )
