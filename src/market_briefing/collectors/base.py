from __future__ import annotations

from dataclasses import dataclass, field

from market_briefing.domain import (
    AtomicFact,
    MarketIndexRecord,
    RawSnapshot,
    SectorSnapshotRecord,
)


@dataclass(frozen=True)
class CollectionResult:
    snapshots: list[RawSnapshot]
    facts: list[AtomicFact]
    market_index_records: list[MarketIndexRecord] = field(default_factory=list)
    sector_snapshot: SectorSnapshotRecord | None = None
