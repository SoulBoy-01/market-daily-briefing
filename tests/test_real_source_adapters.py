from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from market_briefing.audit import verify_snapshot_hash
from market_briefing.collectors.market_data import (
    CHANGE_PCT_DECIMAL_PLACES,
    CLOSE_DECIMAL_PLACES,
    MarketDataCollector,
)
from market_briefing.collectors.official_sources import (
    OfficialSourceCollector,
    OfficialSourceTarget,
)
from market_briefing.domain import (
    FactClassification,
    OfficialCheckResult,
    OfficialCheckStatus,
    ReportType,
    SourceType,
)


class FakeMarketClient:
    provider_id = "synthetic-market-provider"
    provider_name = "合成市场提供方"
    index_source_url = "mock://synthetic-market/indices"
    sector_source_url = "mock://synthetic-market/sectors"
    sector_taxonomy = "synthetic-industry-v1"

    def index_spot(self):
        return [
            {
                "trade_date": "2026-07-02",
                "symbol": "000001.SH",
                "name": "上证指数",
                "close": "3021.45",
                "change_pct": "0.52",
            },
            {
                "trade_date": "2026-07-02",
                "symbol": "399001.SZ",
                "name": "深证成指",
                "close": "9450.12",
                "change_pct": "0.31",
            },
            {
                "trade_date": "2026-07-02",
                "symbol": "399006.SZ",
                "name": "创业板指",
                "close": "2010.33",
                "change_pct": "0.68",
            },
        ]

    def sector_spot(self):
        return [
            {"trade_date": "2026-07-02", "name": "半导体", "change_pct": 2.1},
            {"trade_date": "2026-07-02", "name": "煤炭", "change_pct": -1.4},
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
    assert len(result.market_index_records) == 3
    assert len(result.facts) == 2
    assert {fact.module for fact in result.facts} == {"sector_moves"}
    assert result.facts[0].classification == FactClassification.FACT
    assert result.facts[0].source_type == SourceType.DATA_API
    assert result.facts[0].source_name == "合成市场提供方"
    assert result.market_index_records[0].provider_id == "synthetic-market-provider"
    assert result.market_index_records[0].trade_date == date(2026, 7, 2)
    assert result.market_index_records[0].symbol == "000001.SH"
    assert result.market_index_records[0].close == Decimal("3021.45")
    assert result.sector_snapshot.provider_id == "synthetic-market-provider"
    assert result.sector_snapshot.trade_date == date(2026, 7, 2)
    assert result.sector_snapshot.taxonomy == "synthetic-industry-v1"
    index_snapshot = next(
        snapshot for snapshot in result.snapshots if snapshot.module == "market_indices"
    )
    sector_snapshot = next(
        snapshot for snapshot in result.snapshots if snapshot.module == "sector_moves"
    )
    assert index_snapshot.provider_name == "合成市场提供方"
    assert index_snapshot.metadata["provider_id"] == "synthetic-market-provider"
    assert index_snapshot.metadata["comparison_precision"] == {
        "close_decimal_places": CLOSE_DECIMAL_PLACES,
        "change_pct_decimal_places": CHANGE_PCT_DECIMAL_PLACES,
    }
    assert sector_snapshot.metadata["taxonomy"] == "synthetic-industry-v1"
    assert Path(result.snapshots[0].raw_path).exists()
    assert verify_snapshot_hash(
        Path(result.snapshots[0].raw_path), result.snapshots[0].content_sha256
    )


def test_market_data_collector_sector_fact_ids_are_isolated_by_run(tmp_path):
    collector = MarketDataCollector(client=FakeMarketClient())

    first = collector.collect(
        run_id="run-real-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "sector_moves"],
        raw_dir=tmp_path / "first-raw",
    )
    second = collector.collect(
        run_id="run-real-002",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "sector_moves"],
        raw_dir=tmp_path / "second-raw",
    )

    first_fact_ids = {fact.fact_id for fact in first.facts}
    second_fact_ids = {fact.fact_id for fact in second.facts}

    assert first_fact_ids.isdisjoint(second_fact_ids)
    assert all(fact_id.startswith("fact-run-real-001-") for fact_id in first_fact_ids)
    assert all(fact_id.startswith("fact-run-real-002-") for fact_id in second_fact_ids)
    assert all(fact.module == "sector_moves" for fact in (*first.facts, *second.facts))


def test_market_data_collector_uses_provider_sector_trade_date_not_request_date(tmp_path):
    class StaleSectorClient(FakeMarketClient):
        def sector_spot(self):
            return [
                {"trade_date": "2026-07-01", "name": "半导体", "change_pct": 2.1},
            ]

    result = MarketDataCollector(client=StaleSectorClient()).collect(
        run_id="run-stale-sector",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["sector_moves"],
        raw_dir=tmp_path / "raw",
    )

    assert result.sector_snapshot.trade_date == date(2026, 7, 1)


def test_market_data_collector_preserves_empty_sector_snapshot_for_degraded_gate(tmp_path):
    class EmptySectorClient(FakeMarketClient):
        def sector_spot(self):
            return []

    result = MarketDataCollector(client=EmptySectorClient()).collect(
        run_id="run-empty-sector",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["sector_moves"],
        raw_dir=tmp_path / "raw",
    )

    assert result.sector_snapshot is None
    assert result.facts == []
    assert len(result.snapshots) == 1
    assert result.snapshots[0].metadata["rows"] == 0
    assert Path(result.snapshots[0].raw_path).is_file()


def _official_target(source_name: str, url: str) -> OfficialSourceTarget:
    return OfficialSourceTarget(
        module="policy_regulation",
        source_name=source_name,
        source_url=url,
        source_type=SourceType.EXCHANGE,
    )


ANNOUNCEMENT_HTML = (
    "<html><head><title>监管动态</title></head>"
    "<body><h1>监管动态</h1><p>交易所发布市场监管通报。</p></body></html>"
)


def test_official_source_collector_produces_candidate_instead_of_fact(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ANNOUNCEMENT_HTML, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[_official_target("Mock Exchange", "https://example.test/policy")],
    )

    result = collector.collect(
        run_id="run-official-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "raw",
    )

    assert result.facts == []
    assert len(result.snapshots) == 1
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_id == "candidate-run-official-001-policy_regulation-001"
    assert candidate.snapshot_id == result.snapshots[0].snapshot_id
    assert candidate.module == "policy_regulation"
    assert candidate.title == "监管动态"
    assert candidate.excerpt == "交易所发布市场监管通报。"
    assert candidate.detail_url == "https://example.test/policy"
    assert candidate.suggested_classification == FactClassification.FACT
    assert result.official_checks == (
        OfficialCheckResult(
            source_name="Mock Exchange",
            module="policy_regulation",
            status=OfficialCheckStatus.CANDIDATES_FOUND,
        ),
    )
    assert verify_snapshot_hash(
        Path(result.snapshots[0].raw_path), result.snapshots[0].content_sha256
    )


def test_official_source_collector_candidate_ids_are_isolated_by_run(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ANNOUNCEMENT_HTML, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[_official_target("Mock Exchange", "https://example.test/policy")],
    )

    first = collector.collect(
        run_id="run-official-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "first-raw",
    )
    second = collector.collect(
        run_id="run-official-002",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "second-raw",
    )

    first_ids = {candidate.candidate_id for candidate in first.candidates}
    second_ids = {candidate.candidate_id for candidate in second.candidates}

    assert first_ids.isdisjoint(second_ids)
    assert all(candidate_id.startswith("candidate-run-official-001-") for candidate_id in first_ids)
    assert all(candidate_id.startswith("candidate-run-official-002-") for candidate_id in second_ids)


def test_official_source_collector_degrades_failed_source_to_check_failed(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/down":
            return httpx.Response(500, request=request)
        return httpx.Response(200, html=ANNOUNCEMENT_HTML, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[
            _official_target("Down Exchange", "https://example.test/down"),
            _official_target("Healthy Exchange", "https://example.test/healthy"),
        ],
    )

    result = collector.collect(
        run_id="run-official-500",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "raw",
    )

    statuses = {check.source_name: check.status for check in result.official_checks}
    assert statuses["Down Exchange"] == OfficialCheckStatus.CHECK_FAILED
    assert statuses["Healthy Exchange"] == OfficialCheckStatus.CANDIDATES_FOUND
    assert len(result.snapshots) == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].snapshot_id == result.snapshots[0].snapshot_id


def test_official_source_collector_reports_no_updates_for_contentless_page(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            html="<html><head></head><body><div>导航菜单</div></body></html>",
            request=request,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[_official_target("Mock Exchange", "https://example.test/policy")],
    )

    result = collector.collect(
        run_id="run-official-empty",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["policy_regulation"],
        raw_dir=tmp_path / "raw",
    )

    assert len(result.snapshots) == 1
    assert result.candidates == ()
    assert result.official_checks == (
        OfficialCheckResult(
            source_name="Mock Exchange",
            module="policy_regulation",
            status=OfficialCheckStatus.CHECKED_NO_UPDATES,
        ),
    )


def test_official_source_collector_skips_disabled_targets_without_http_call(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled target should not be fetched")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    collector = OfficialSourceCollector(
        client=http_client,
        targets=[_official_target("Mock Exchange", "https://example.test/policy")],
    )

    result = collector.collect(
        run_id="run-official-disabled",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
        raw_dir=tmp_path / "raw",
    )

    assert result.snapshots == []
    assert result.facts == []
    assert result.candidates == ()
    assert result.official_checks == ()
