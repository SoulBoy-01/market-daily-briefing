from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    ReportType,
    SourceType,
)


class FixtureCollector:
    def __init__(self, fixture_path: Path):
        self.fixture_path = fixture_path

    def collect(
        self,
        run_id: str,
        report_date: str,
        report_type: ReportType,
        enabled_modules: list[str],
        raw_dir: Path,
    ) -> CollectionResult:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        enabled_module_set = set(enabled_modules)
        fetched_at = datetime.now(timezone.utc)
        snapshots: list[RawSnapshot] = []
        facts: list[AtomicFact] = []

        for index, source in enumerate(payload["sources"], start=1):
            module = source["module"]
            if module not in enabled_module_set:
                continue

            raw_path = _write_raw_snapshot(
                raw_dir=raw_dir,
                report_date=report_date,
                run_id=run_id,
                module=module,
                content=source["content"],
                content_type=source["content_type"],
            )
            source_type = SourceType(source["source_type"])
            snapshot = RawSnapshot(
                snapshot_id=f"{run_id}-{index:03d}-{module}",
                run_id=run_id,
                module=module,
                source_name=source["source_name"],
                source_url=source["source_url"],
                source_type=source_type,
                fetched_at=fetched_at,
                content_type=source["content_type"],
                raw_path=str(raw_path),
                metadata={
                    "fixture_path": self.fixture_path.as_posix(),
                    "fact_count": len(source.get("facts", [])),
                },
            )
            snapshots.append(snapshot)

            published_at = datetime.fromisoformat(source["published_at"])
            for fact_payload in source.get("facts", []):
                facts.append(
                    AtomicFact(
                        fact_id=fact_payload["fact_id"],
                        run_id=run_id,
                        report_date=report_date,
                        report_type=report_type,
                        module=module,
                        claim=fact_payload["claim"],
                        classification=FactClassification(fact_payload["classification"]),
                        source_name=source["source_name"],
                        source_url=source["source_url"],
                        source_type=source_type,
                        published_at=published_at,
                        fetched_at=fetched_at,
                        confidence=fact_payload["confidence"],
                        raw_snapshot_path=str(raw_path),
                        derived_from_fact_ids=fact_payload.get("derived_from_fact_ids", []),
                        used_in_sections=fact_payload.get("used_in_sections", [module]),
                    )
                )

        return CollectionResult(snapshots=snapshots, facts=facts)


def _write_raw_snapshot(
    raw_dir: Path,
    report_date: str,
    run_id: str,
    module: str,
    content: Any,
    content_type: str,
) -> Path:
    module_dir = raw_dir / report_date / run_id
    module_dir.mkdir(parents=True, exist_ok=True)
    suffix = "json" if content_type == "application/json" else "html"
    raw_path = module_dir / f"{module}.{suffix}"
    raw_path.write_text(_render_raw_content(content, content_type), encoding="utf-8")
    return raw_path


def _render_raw_content(content: Any, content_type: str) -> str:
    if content_type == "application/json":
        return json.dumps(content, ensure_ascii=False, indent=2)
    return str(content)
