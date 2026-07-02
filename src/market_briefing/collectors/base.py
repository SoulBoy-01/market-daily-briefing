from __future__ import annotations

from dataclasses import dataclass

from market_briefing.domain import AtomicFact, RawSnapshot


@dataclass(frozen=True)
class CollectionResult:
    snapshots: list[RawSnapshot]
    facts: list[AtomicFact]
