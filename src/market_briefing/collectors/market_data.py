from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from market_briefing.audit import SAFE_RUN_ID_RE, SnapshotFile, run_directory, write_snapshot_text
from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    MarketIndexRecord,
    RawSnapshot,
    ReportType,
    SectorSnapshotRecord,
    SourceType,
)
from market_briefing.reconciliation import (
    CHANGE_PCT_DECIMAL_PLACES,
    CLOSE_DECIMAL_PLACES,
)


class MarketDataClient(Protocol):
    provider_id: str
    provider_name: str
    index_source_url: str
    sector_source_url: str
    sector_taxonomy: str

    def index_spot(self) -> list[dict[str, Any]]:
        ...

    def sector_spot(self) -> list[dict[str, Any]]:
        ...


class MarketDataCollector:
    def __init__(self, client: MarketDataClient):
        self.client = client

    def collect(
        self,
        run_id: str,
        report_date: str,
        report_type: ReportType,
        enabled_modules: list[str],
        raw_dir: Path,
    ) -> CollectionResult:
        fetched_at = datetime.now(timezone.utc)
        enabled_module_set = set(enabled_modules)
        snapshots: list[RawSnapshot] = []
        facts: list[AtomicFact] = []
        market_index_records: list[MarketIndexRecord] = []
        sector_snapshot: SectorSnapshotRecord | None = None
        provider_id = _provider_id(self.client.provider_id)

        if "market_indices" in enabled_module_set:
            rows = self.client.index_spot()
            snapshot_file = _write_json(
                raw_dir,
                report_date,
                run_id,
                f"{provider_id}-market_indices",
                rows,
            )
            snapshot = _snapshot(
                run_id=run_id,
                module="market_indices",
                provider_id=provider_id,
                provider_name=self.client.provider_name,
                source_url=self.client.index_source_url,
                snapshot_file=snapshot_file,
                fetched_at=fetched_at,
                row_count=len(rows),
                metadata={
                    "comparison_precision": {
                        "close_decimal_places": CLOSE_DECIMAL_PLACES,
                        "change_pct_decimal_places": CHANGE_PCT_DECIMAL_PLACES,
                    }
                },
            )
            snapshots.append(snapshot)
            market_index_records.extend(
                MarketIndexRecord(
                    provider_id=provider_id,
                    trade_date=date.fromisoformat(str(row["trade_date"])),
                    symbol=str(row["symbol"]),
                    close=Decimal(str(row["close"])),
                    change_pct=Decimal(str(row["change_pct"])),
                    evidence_id=snapshot.snapshot_id,
                )
                for row in rows
            )

        if "sector_moves" in enabled_module_set:
            rows = self.client.sector_spot()
            snapshot_file = _write_json(
                raw_dir,
                report_date,
                run_id,
                f"{provider_id}-sector_moves",
                rows,
            )
            snapshot = _snapshot(
                run_id=run_id,
                module="sector_moves",
                provider_id=provider_id,
                provider_name=self.client.provider_name,
                source_url=self.client.sector_source_url,
                snapshot_file=snapshot_file,
                fetched_at=fetched_at,
                row_count=len(rows),
                metadata={"taxonomy": self.client.sector_taxonomy},
            )
            snapshots.append(snapshot)
            sector_trade_dates = {
                date.fromisoformat(str(row["trade_date"])) for row in rows
            }
            if len(sector_trade_dates) > 1:
                raise ValueError("sector rows must contain one trade_date")
            if sector_trade_dates:
                sector_snapshot = SectorSnapshotRecord(
                    provider_id=provider_id,
                    trade_date=sector_trade_dates.pop(),
                    taxonomy=self.client.sector_taxonomy,
                    evidence_id=snapshot.snapshot_id,
                )
            facts.extend(
                _sector_fact(
                    run_id=run_id,
                    report_date=report_date,
                    report_type=report_type,
                    row=row,
                    row_index=index,
                    raw_path=snapshot_file.path,
                    fetched_at=fetched_at,
                    provider_name=self.client.provider_name,
                    source_url=self.client.sector_source_url,
                    taxonomy=self.client.sector_taxonomy,
                )
                for index, row in enumerate(rows, start=1)
            )

        return CollectionResult(
            snapshots=snapshots,
            facts=facts,
            market_index_records=market_index_records,
            sector_snapshot=sector_snapshot,
        )


def _write_json(
    raw_dir: Path,
    report_date: str,
    run_id: str,
    module: str,
    rows: list[dict[str, Any]],
) -> SnapshotFile:
    raw_path = run_directory(raw_dir, report_date, run_id) / f"{module}.json"
    return write_snapshot_text(raw_path, json.dumps(rows, ensure_ascii=False, indent=2))


def _snapshot(
    run_id: str,
    module: str,
    provider_id: str,
    provider_name: str,
    source_url: str,
    snapshot_file: SnapshotFile,
    fetched_at: datetime,
    row_count: int,
    metadata: dict[str, Any],
) -> RawSnapshot:
    return RawSnapshot(
        snapshot_id=f"{run_id}-{provider_id}-{module}",
        run_id=run_id,
        module=module,
        source_name=provider_name,
        source_url=source_url,
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name=provider_name,
        license_ref=None,
        metadata={"rows": row_count, "provider_id": provider_id, **metadata},
    )


def _sector_fact(
    run_id: str,
    report_date: str,
    report_type: ReportType,
    row: dict[str, Any],
    row_index: int,
    raw_path: Path,
    fetched_at: datetime,
    provider_name: str,
    source_url: str,
    taxonomy: str,
) -> AtomicFact:
    return AtomicFact(
        fact_id=f"fact-{run_id}-sector-{row_index:03d}",
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        module="sector_moves",
        claim=(
            f"按 {taxonomy} 口径，{row['name']}板块涨跌幅为 {row['change_pct']}%。"
        ),
        classification=FactClassification.FACT,
        source_name=provider_name,
        source_url=source_url,
        source_type=SourceType.DATA_API,
        published_at=None,
        fetched_at=fetched_at,
        confidence="medium",
        raw_snapshot_path=str(raw_path),
        used_in_sections=["sector_moves"],
    )


def _provider_id(value: str) -> str:
    if not SAFE_RUN_ID_RE.fullmatch(value):
        raise ValueError("provider_id must contain only letters, numbers, underscore, or hyphen")
    return value
