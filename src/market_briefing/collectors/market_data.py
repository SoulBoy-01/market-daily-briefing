from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from market_briefing.audit import SnapshotFile, run_directory, write_snapshot_text
from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    ReportType,
    SourceType,
)


class MarketDataClient(Protocol):
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

        if "market_indices" in enabled_module_set:
            rows = self.client.index_spot()
            snapshot_file = _write_json(raw_dir, report_date, run_id, "market_indices", rows)
            snapshots.append(
                _snapshot(
                    run_id=run_id,
                    module="market_indices",
                    source_url="akshare://index_spot",
                    snapshot_file=snapshot_file,
                    fetched_at=fetched_at,
                    row_count=len(rows),
                )
            )
            facts.extend(
                _index_fact(
                    run_id=run_id,
                    report_date=report_date,
                    report_type=report_type,
                    row=row,
                    row_index=index,
                    raw_path=snapshot_file.path,
                    fetched_at=fetched_at,
                )
                for index, row in enumerate(rows, start=1)
            )

        if "sector_moves" in enabled_module_set:
            rows = self.client.sector_spot()
            snapshot_file = _write_json(raw_dir, report_date, run_id, "sector_moves", rows)
            snapshots.append(
                _snapshot(
                    run_id=run_id,
                    module="sector_moves",
                    source_url="akshare://sector_spot",
                    snapshot_file=snapshot_file,
                    fetched_at=fetched_at,
                    row_count=len(rows),
                )
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
                )
                for index, row in enumerate(rows, start=1)
            )

        return CollectionResult(snapshots=snapshots, facts=facts)


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
    source_url: str,
    snapshot_file: SnapshotFile,
    fetched_at: datetime,
    row_count: int,
) -> RawSnapshot:
    return RawSnapshot(
        snapshot_id=f"{run_id}-{module}",
        run_id=run_id,
        module=module,
        source_name="AkShare adapter",
        source_url=source_url,
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(snapshot_file.path),
        content_sha256=snapshot_file.content_sha256,
        provider_name="AkShare adapter",
        license_ref=None,
        metadata={"rows": row_count},
    )


def _index_fact(
    run_id: str,
    report_date: str,
    report_type: ReportType,
    row: dict[str, Any],
    row_index: int,
    raw_path: Path,
    fetched_at: datetime,
) -> AtomicFact:
    return AtomicFact(
        fact_id=f"fact-{run_id}-market-index-{row_index:03d}",
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        module="market_indices",
        claim=f"{row['name']}收于 {row['close']} 点，涨幅 {row['change_pct']}%。",
        classification=FactClassification.FACT,
        source_name="AkShare adapter",
        source_url="akshare://index_spot",
        source_type=SourceType.DATA_API,
        published_at=None,
        fetched_at=fetched_at,
        confidence="medium",
        raw_snapshot_path=str(raw_path),
        used_in_sections=["market_indices"],
    )


def _sector_fact(
    run_id: str,
    report_date: str,
    report_type: ReportType,
    row: dict[str, Any],
    row_index: int,
    raw_path: Path,
    fetched_at: datetime,
) -> AtomicFact:
    return AtomicFact(
        fact_id=f"fact-{run_id}-sector-{row_index:03d}",
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        module="sector_moves",
        claim=f"{row['name']}板块涨跌幅为 {row['change_pct']}%。",
        classification=FactClassification.FACT,
        source_name="AkShare adapter",
        source_url="akshare://sector_spot",
        source_type=SourceType.DATA_API,
        published_at=None,
        fetched_at=fetched_at,
        confidence="medium",
        raw_snapshot_path=str(raw_path),
        used_in_sections=["sector_moves"],
    )
