from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


def _to_record_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_record_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_record_value(item) for item in value]
    return value


class ReportType(StrEnum):
    AFTER_CLOSE = "after_close"
    PRE_OPEN_UPDATE = "pre_open_update"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


RUN_STATUS_TRANSITIONS = MappingProxyType(
    {
        RunStatus.CREATED: frozenset({RunStatus.RUNNING}),
        RunStatus.RUNNING: frozenset(
            {
                RunStatus.AWAITING_REVIEW,
                RunStatus.COMPLETED,
                RunStatus.COMPLETED_WITH_WARNINGS,
                RunStatus.FAILED,
            }
        ),
        RunStatus.AWAITING_REVIEW: frozenset(
            {
                RunStatus.COMPLETED,
                RunStatus.COMPLETED_WITH_WARNINGS,
                RunStatus.FAILED,
            }
        ),
        RunStatus.COMPLETED: frozenset(),
        RunStatus.COMPLETED_WITH_WARNINGS: frozenset(),
        RunStatus.FAILED: frozenset(),
    }
)


def can_transition_run(current: RunStatus, target: RunStatus) -> bool:
    return target in RUN_STATUS_TRANSITIONS[current]


class FactClassification(StrEnum):
    FACT = "fact"
    OPINION = "opinion"
    INFERENCE = "inference"
    UNVERIFIED = "unverified"


class CandidateReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ModuleCoverageStatus(StrEnum):
    COVERED = "covered"
    NO_UPDATES = "no_updates"
    PENDING_REVIEW = "pending_review"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class SourceType(StrEnum):
    OFFICIAL = "official"
    EXCHANGE = "exchange"
    MEDIA = "media"
    DATA_API = "data_api"
    OTHER = "other"


@dataclass(frozen=True)
class RawSnapshot:
    snapshot_id: str
    run_id: str
    module: str
    source_name: str
    source_url: str
    source_type: SourceType
    fetched_at: datetime
    content_type: str
    raw_path: str
    content_sha256: str = ""
    provider_name: str = ""
    license_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_value(self.metadata))

    def to_record(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "module": self.module,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type.value,
            "fetched_at": self.fetched_at.isoformat(),
            "content_type": self.content_type,
            "raw_path": self.raw_path,
            "content_sha256": self.content_sha256,
            "provider_name": self.provider_name,
            "license_ref": self.license_ref,
            "metadata": _to_record_value(self.metadata),
        }


@dataclass(frozen=True)
class AtomicFact:
    fact_id: str
    run_id: str
    report_date: str
    report_type: ReportType
    module: str
    claim: str
    classification: FactClassification
    source_name: str
    source_url: str
    source_type: SourceType
    published_at: datetime | None
    fetched_at: datetime
    confidence: str
    raw_snapshot_path: str
    derived_from_fact_ids: tuple[str, ...] = field(default_factory=tuple)
    used_in_sections: tuple[str, ...] = field(default_factory=tuple)
    source_candidate_id: str | None = None
    source_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived_from_fact_ids", tuple(self.derived_from_fact_ids))
        object.__setattr__(self, "used_in_sections", tuple(self.used_in_sections))

    def to_record(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "run_id": self.run_id,
            "report_date": self.report_date,
            "report_type": self.report_type.value,
            "module": self.module,
            "claim": self.claim,
            "classification": self.classification.value,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type.value,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "fetched_at": self.fetched_at.isoformat(),
            "confidence": self.confidence,
            "raw_snapshot_path": self.raw_snapshot_path,
            "derived_from_fact_ids": list(self.derived_from_fact_ids),
            "used_in_sections": list(self.used_in_sections),
            "source_candidate_id": self.source_candidate_id,
            "source_snapshot_id": self.source_snapshot_id,
        }


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    run_id: str
    snapshot_id: str
    module: str
    title: str
    detail_url: str
    published_at: datetime | None
    excerpt: str
    suggested_classification: FactClassification
    created_at: datetime

    def to_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "module": self.module,
            "title": self.title,
            "detail_url": self.detail_url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "excerpt": self.excerpt,
            "suggested_classification": self.suggested_classification.value,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class CandidateReviewEvent:
    event_id: int
    candidate_id: str
    from_status: CandidateReviewStatus | None
    to_status: CandidateReviewStatus
    reviewed_at: datetime
    reviewer_id: str | None
    note: str
    approved_fact_id: str | None = None


@dataclass(frozen=True)
class RunWarning:
    warning_id: str
    run_id: str
    source_name: str
    module: str
    message: str
    detail: str | None
    created_at: datetime

    def to_record(self) -> dict[str, Any]:
        return {
            "warning_id": self.warning_id,
            "run_id": self.run_id,
            "source_name": self.source_name,
            "module": self.module,
            "message": self.message,
            "detail": self.detail,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ModuleCoverage:
    coverage_id: str
    run_id: str
    module: str
    status: ModuleCoverageStatus
    source_name: str | None
    message: str
    recorded_at: datetime

    def to_record(self) -> dict[str, Any]:
        return {
            "coverage_id": self.coverage_id,
            "run_id": self.run_id,
            "module": self.module,
            "status": self.status.value,
            "source_name": self.source_name,
            "message": self.message,
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True)
class FactLine:
    fact_id: str
    classification: FactClassification
    claim: str
    derived_from_fact_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "classification", FactClassification(self.classification))
        object.__setattr__(self, "derived_from_fact_ids", tuple(self.derived_from_fact_ids))


@dataclass(frozen=True)
class ReportSection:
    section_id: str
    title: str
    body: str
    fact_ids: tuple[str, ...]
    status: str
    fact_lines: tuple[FactLine, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_ids", tuple(self.fact_ids))
        object.__setattr__(self, "fact_lines", tuple(self.fact_lines))


@dataclass(frozen=True)
class Report:
    report_id: str
    run_id: str
    report_date: str
    report_type: ReportType
    title: str
    sections: tuple[ReportSection, ...]
    markdown_path: str
    html_path: str
    fact_ledger_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))

    def all_fact_ids(self) -> set[str]:
        return {fact_id for section in self.sections for fact_id in section.fact_ids}


@dataclass(frozen=True)
class FeedbackEntry:
    feedback_id: str
    report_id: str
    section_id: str
    score: int
    tags: tuple[str, ...]
    note: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))

    def summary_line(self) -> str:
        tag_text = ",".join(self.tags)
        return f"{self.section_id}: score={self.score}; tags={tag_text}; note={self.note}"


@dataclass(frozen=True)
class Run:
    run_id: str
    report_date: str
    report_type: ReportType
    enabled_modules: tuple[str, ...]
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    warning_count: int = 0
    error_message: str | None = None
    supersedes_run_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled_modules", tuple(self.enabled_modules))

    @classmethod
    def create(
        cls,
        run_id: str,
        report_date: str,
        report_type: ReportType,
        enabled_modules: list[str],
    ) -> Run:
        return cls(
            run_id=run_id,
            report_date=report_date,
            report_type=report_type,
            enabled_modules=tuple(enabled_modules),
            status=RunStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class RunEvent:
    event_id: int
    run_id: str
    from_status: RunStatus | None
    to_status: RunStatus
    created_at: datetime
