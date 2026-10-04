from __future__ import annotations

from dataclasses import dataclass, field

from market_briefing.domain import (
    AtomicFact,
    EvidenceCandidate,
    MarketIndexRecord,
    OfficialCheckResult,
    RawSnapshot,
    SectorSnapshotRecord,
)


@dataclass(frozen=True)
class CollectionResult:
    snapshots: list[RawSnapshot]
    facts: list[AtomicFact]
    candidates: tuple[EvidenceCandidate, ...] = ()
    official_checks: tuple[OfficialCheckResult, ...] = ()
    market_index_records: list[MarketIndexRecord] = field(default_factory=list)
    sector_snapshot: SectorSnapshotRecord | None = None
