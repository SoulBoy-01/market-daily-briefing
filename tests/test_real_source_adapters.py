from pathlib import Path

import httpx

from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.collectors.official_sources import (
    OfficialSourceCollector,
    OfficialSourceTarget,
)
from market_briefing.domain import FactClassification, ReportType, SourceType


class FakeMarketClient:
    def index_spot(self):
        return [
            {"name": "上证指数", "close": 3021.45, "change_pct": 0.52},
            {"name": "深证成指", "close": 9450.12, "change_pct": 0.31},
        ]

    def sector_spot(self):
        return [
            {"name": "半导体", "change_pct": 2.1},
            {"name": "煤炭", "change_pct": -1.4},
        ]


def test_market_data_collector_normalizes_indices_and_sectors(tmp_path):
    collector = MarketDataCollector(client=FakeMarketClient())

    result = collector.collect(
        run_id="run-real-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "sector_moves"],
        raw_dir=tmp_path / "raw",
    )

    assert len(result.snapshots) == 2
    assert len(result.facts) == 4
    assert result.facts[0].classification == FactClassification.FACT
    assert result.facts[0].source_type == SourceType.DATA_API
    assert Path(result.snapshots[0].raw_path).exists()


def test_official_source_collector_extracts_official_fact(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            html="<html><head><title>监管动态</title></head><body><h1>监管动态</h1><p>交易所发布市场监管通报。</p></body></html>",
            request=request,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[
            OfficialSourceTarget(
                module="policy_regulation",
                source_name="Mock Exchange",
                source_url="https://example.test/policy",
                source_type=SourceType.EXCHANGE,
            )
        ],
    )

    result = collector.collect(
        run_id="run-official-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "raw",
    )

    assert len(result.snapshots) == 1
    assert len(result.facts) == 1
    assert result.facts[0].claim == "监管动态：交易所发布市场监管通报。"
    assert result.facts[0].source_type == SourceType.EXCHANGE
