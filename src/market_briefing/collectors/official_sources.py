from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from market_briefing.audit import SnapshotFile, run_directory, write_snapshot_text
from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    EvidenceCandidate,
    FactClassification,
    OfficialCheckResult,
    OfficialCheckStatus,
    RawSnapshot,
    ReportType,
    SourceType,
)


@dataclass(frozen=True)
class OfficialSourceTarget:
    module: str
    source_name: str
    source_url: str
    source_type: SourceType


class OfficialSourceCollector:
    def __init__(self, client: httpx.Client, targets: list[OfficialSourceTarget]):
        self.client = client
        self.targets = targets

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
        candidates: list[EvidenceCandidate] = []
        official_checks: list[OfficialCheckResult] = []

        for index, target in enumerate(self.targets, start=1):
            if target.module not in enabled_module_set:
                continue

            try:
                response = self.client.get(target.source_url, timeout=15)
                response.raise_for_status()
            except httpx.HTTPError:
                official_checks.append(
                    OfficialCheckResult(
                        source_name=target.source_name,
                        module=target.module,
                        status=OfficialCheckStatus.CHECK_FAILED,
                    )
                )
                continue

            snapshot_file = _write_html(
                raw_dir=raw_dir,
                report_date=report_date,
                run_id=run_id,
                module=target.module,
                source_index=index,
                html=response.text,
            )
            snapshot = RawSnapshot(
                snapshot_id=f"{run_id}-{target.module}-{index:03d}",
                run_id=run_id,
                module=target.module,
                source_name=target.source_name,
                source_url=target.source_url,
                source_type=target.source_type,
                fetched_at=fetched_at,
                content_type="text/html",
                raw_path=str(snapshot_file.path),
                content_sha256=snapshot_file.content_sha256,
                provider_name=target.source_name,
                license_ref=None,
                metadata={},
            )
            snapshots.append(snapshot)

            title, excerpt = _extract_title_and_excerpt(response.text)
            if title is None:
                official_checks.append(
                    OfficialCheckResult(
                        source_name=target.source_name,
                        module=target.module,
                        status=OfficialCheckStatus.CHECKED_NO_UPDATES,
                    )
                )
                continue

            candidates.append(
                EvidenceCandidate(
                    candidate_id=f"candidate-{run_id}-{target.module}-{index:03d}",
                    run_id=run_id,
                    snapshot_id=snapshot.snapshot_id,
                    module=target.module,
                    title=title,
                    detail_url=target.source_url,
                    published_at=None,
                    excerpt=excerpt,
                    suggested_classification=FactClassification.FACT,
                    created_at=fetched_at,
                )
            )
            official_checks.append(
                OfficialCheckResult(
                    source_name=target.source_name,
                    module=target.module,
                    status=OfficialCheckStatus.CANDIDATES_FOUND,
                )
            )

        return CollectionResult(
            snapshots=snapshots,
            facts=[],
            candidates=tuple(candidates),
            official_checks=tuple(official_checks),
        )


def default_official_targets() -> list[OfficialSourceTarget]:
    return [
        OfficialSourceTarget(
            "policy_regulation",
            "中国证监会",
            "https://www.csrc.gov.cn/",
            SourceType.OFFICIAL,
        ),
        OfficialSourceTarget(
            "policy_regulation",
            "上海证券交易所",
            "https://www.sse.com.cn/",
            SourceType.EXCHANGE,
        ),
        OfficialSourceTarget(
            "policy_regulation",
            "深圳证券交易所",
            "https://www.szse.cn/",
            SourceType.EXCHANGE,
        ),
    ]


def _write_html(
    raw_dir: Path,
    report_date: str,
    run_id: str,
    module: str,
    source_index: int,
    html: str,
) -> SnapshotFile:
    raw_path = run_directory(raw_dir, report_date, run_id) / f"{module}-{source_index:03d}.html"
    return write_snapshot_text(raw_path, html)


def _extract_title_and_excerpt(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h1") or soup.find("title")
    paragraph_node = soup.find("p")
    title = title_node.get_text(strip=True) if title_node else None
    paragraph = paragraph_node.get_text(strip=True) if paragraph_node else None
    if not title:
        return None, None
    return title, paragraph or title
