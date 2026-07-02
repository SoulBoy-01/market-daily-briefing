from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
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
        facts: list[AtomicFact] = []

        for index, target in enumerate(self.targets, start=1):
            if target.module not in enabled_module_set:
                continue

            response = self.client.get(target.source_url, timeout=15)
            response.raise_for_status()

            raw_path = _write_html(
                raw_dir=raw_dir,
                report_date=report_date,
                run_id=run_id,
                module=target.module,
                source_index=index,
                html=response.text,
            )
            title, first_paragraph = _extract_title_and_first_paragraph(response.text)

            snapshots.append(
                RawSnapshot(
                    snapshot_id=f"{run_id}-{target.module}-{index:03d}",
                    run_id=run_id,
                    module=target.module,
                    source_name=target.source_name,
                    source_url=target.source_url,
                    source_type=target.source_type,
                    fetched_at=fetched_at,
                    content_type="text/html",
                    raw_path=str(raw_path),
                    metadata={"title": title},
                )
            )
            facts.append(
                AtomicFact(
                    fact_id=f"fact-{target.module}-{index:03d}",
                    run_id=run_id,
                    report_date=report_date,
                    report_type=report_type,
                    module=target.module,
                    claim=f"{title}：{first_paragraph}",
                    classification=FactClassification.FACT,
                    source_name=target.source_name,
                    source_url=target.source_url,
                    source_type=target.source_type,
                    published_at=None,
                    fetched_at=fetched_at,
                    confidence="high",
                    raw_snapshot_path=str(raw_path),
                    used_in_sections=[target.module],
                )
            )

        return CollectionResult(snapshots=snapshots, facts=facts)


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
) -> Path:
    raw_path = raw_dir / report_date / run_id / f"{module}-{source_index:03d}.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(html, encoding="utf-8")
    return raw_path


def _extract_title_and_first_paragraph(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1") or soup.find("title")
    paragraph = soup.find("p")
    title_text = title.get_text(strip=True) if title else "官方信息"
    paragraph_text = paragraph.get_text(strip=True) if paragraph else "页面已抓取，需人工复核正文。"
    return title_text, paragraph_text
