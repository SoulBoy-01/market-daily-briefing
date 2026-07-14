from __future__ import annotations

from market_briefing.domain import (
    AtomicFact,
    CandidateReviewEvent,
    CandidateReviewStatus,
    EvidenceCandidate,
    FactClassification,
    RawSnapshot,
    ReportType,
)


class CandidateNotApprovedError(ValueError):
    pass


class CandidateSnapshotMismatchError(ValueError):
    pass


class UnpublishableCandidateError(ValueError):
    pass


def build_fact_from_approved_candidate(
    *,
    candidate: EvidenceCandidate,
    review_event: CandidateReviewEvent,
    snapshot: RawSnapshot,
    report_date: str,
    report_type: ReportType,
) -> AtomicFact:
    if (
        review_event.candidate_id != candidate.candidate_id
        or review_event.to_status != CandidateReviewStatus.APPROVED
        or not review_event.approved_fact_id
    ):
        raise CandidateNotApprovedError(candidate.candidate_id)
    if (
        snapshot.snapshot_id != candidate.snapshot_id
        or snapshot.run_id != candidate.run_id
        or snapshot.module != candidate.module
    ):
        raise CandidateSnapshotMismatchError(candidate.candidate_id)
    if candidate.suggested_classification == FactClassification.UNVERIFIED:
        raise UnpublishableCandidateError(candidate.candidate_id)

    return AtomicFact(
        fact_id=review_event.approved_fact_id,
        run_id=candidate.run_id,
        report_date=report_date,
        report_type=report_type,
        module=candidate.module,
        claim=candidate.excerpt,
        classification=candidate.suggested_classification,
        source_name=snapshot.source_name,
        source_url=candidate.detail_url,
        source_type=snapshot.source_type,
        published_at=candidate.published_at,
        fetched_at=snapshot.fetched_at,
        confidence="high",
        raw_snapshot_path=snapshot.raw_path,
        source_candidate_id=candidate.candidate_id,
        source_snapshot_id=snapshot.snapshot_id,
    )
