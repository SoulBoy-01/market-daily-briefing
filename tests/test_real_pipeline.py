from pathlib import Path

import httpx
import pytest

from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.collectors.official_sources import (
    OfficialSourceCollector,
    OfficialSourceTarget,
)
from market_briefing.config import AppConfig
from market_briefing.domain import (
    CandidateReviewStatus,
    ModuleCoverageStatus,
    ReportType,
    RunStatus,
    SourceType,
)
from market_briefing.real_pipeline import (
    RealAfterCloseRequest,
    RealModeDisabledError,
    collect_real_after_close,
    publish_real_after_close,
)
from market_briefing.sources import load_source_registry
from market_briefing.storage import BriefingStore


class FakeIndexClient:
    def __init__(self, provider_id: str, close: str):
        self.provider_id = provider_id
        self.provider_name = f"合成提供方 {provider_id}"
        self.index_source_url = f"mock://{provider_id}/indices"
        self.sector_source_url = f"mock://{provider_id}/sectors"
        self.sector_taxonomy = "synthetic-industry-v1"
        self._close = close

    def index_spot(self):
        return [
            {
                "trade_date": "2026-07-02",
                "symbol": symbol,
                "close": self._close,
                "change_pct": "0.52",
            }
            for symbol in ("000001.SH", "399001.SZ", "399006.SZ")
        ]

    def sector_spot(self):
        return [{"trade_date": "2026-07-02", "name": "半导体", "change_pct": 2.1}]


class StaticOfficialClient:
    """不联网的官方来源替身：返回固定 HTML，不触碰网络。"""

    HTML = (
        "<html><head><title>监管动态</title></head>"
        "<body><h1>监管动态</h1><p>交易所发布市场监管通报。</p></body></html>"
    )

    def __init__(self):
        self.requested_urls: list[str] = []

    def get(self, url: str, timeout: int = 15):
        self.requested_urls.append(url)
        return _StaticResponse(self.HTML)


class _StaticResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        database_path=tmp_path / "briefing.sqlite",
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        generation_provider="template",
        report_modules={
            ReportType.AFTER_CLOSE: {
                "market_indices": True,
                "sector_moves": True,
                "policy_regulation": True,
            },
            ReportType.PRE_OPEN_UPDATE: {},
        },
    )


def _store(tmp_path: Path) -> BriefingStore:
    store = BriefingStore(
        tmp_path / "briefing.sqlite",
        trusted_roots=(tmp_path / "raw", tmp_path / "reports"),
    )
    store.initialize()
    return store


def _request(run_id: str = "run-real-001") -> RealAfterCloseRequest:
    return RealAfterCloseRequest(
        run_id=run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
    )


def test_real_request_rejects_pre_open_update():
    with pytest.raises(ValueError, match="after_close"):
        RealAfterCloseRequest(
            run_id="run-pre-open",
            report_date="2026-07-02",
            report_type=ReportType.PRE_OPEN_UPDATE,
        )


def test_collect_real_blocks_when_registry_lacks_independent_api(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(RealModeDisabledError, match="independent_api"):
        collect_real_after_close(
            request=_request("run-locked"),
            config=_config(tmp_path),
            store=store,
            registry=load_source_registry(Path("configs/sources.yaml")),
            market_clients=(
                MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
                MarketDataCollector(client=FakeIndexClient("vendor", "3021.45")),
            ),
            official_collector=None,
        )

    assert store.get_run("run-locked") is None


def test_collect_real_parks_run_for_review_when_candidates_found(tmp_path):
    store = _store(tmp_path)
    config = _config(tmp_path)
    registry = _dual_sourced_registry(tmp_path)

    result = collect_real_after_close(
        request=_request("run-collect"),
        config=config,
        store=store,
        registry=registry,
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
            MarketDataCollector(client=FakeIndexClient("vendor", "3021.45")),
        ),
        official_collector=OfficialSourceCollector(
            client=StaticOfficialClient(),
            targets=[
                OfficialSourceTarget(
                    module="policy_regulation",
                    source_name="合成交易所",
                    source_url="fixture://policy",
                    source_type=SourceType.EXCHANGE,
                )
            ],
        ),
    )

    assert result.status == RunStatus.AWAITING_REVIEW
    assert store.get_run("run-collect").status == RunStatus.AWAITING_REVIEW
    snapshots = store.list_snapshots("run-collect")
    assert {snapshot.module for snapshot in snapshots} == {
        "market_indices",
        "sector_moves",
        "policy_regulation",
    }
    assert len(store.list_facts("run-collect")) == 0
    assert len(result.candidate_ids) == 1


def test_publish_real_refuses_while_candidates_pending(tmp_path):
    store = _store(tmp_path)
    config = _config(tmp_path)
    registry = _dual_sourced_registry(tmp_path)
    collect_real_after_close(
        request=_request("run-pending"),
        config=config,
        store=store,
        registry=registry,
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
            MarketDataCollector(client=FakeIndexClient("vendor", "3021.45")),
        ),
        official_collector=OfficialSourceCollector(
            client=StaticOfficialClient(),
            targets=[
                OfficialSourceTarget(
                    module="policy_regulation",
                    source_name="合成交易所",
                    source_url="fixture://policy",
                    source_type=SourceType.EXCHANGE,
                )
            ],
        ),
    )
    candidate_id = _pending_candidate_id(store, "run-pending")

    with pytest.raises(RuntimeError, match="待审核"):
        publish_real_after_close(
            request=_request("run-pending"),
            config=config,
            store=store,
        )

    assert store.get_run("run-pending").status == RunStatus.AWAITING_REVIEW
    assert store.candidate_review_status(candidate_id) == CandidateReviewStatus.PENDING


def _pending_candidate_id(store: BriefingStore, run_id: str) -> str:
    with store.connection() as connection:
        row = connection.execute(
            "select candidate_id from evidence_candidates where run_id = ?",
            (run_id,),
        ).fetchone()
    return row["candidate_id"]


def _dual_sourced_registry(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        """
sources:
  - provider_id: sse-official
    provider_name: 上海证券交易所
    provider_kind: exchange_official
    module: market_indices
    symbols: [000001.SH, 399001.SZ, 399006.SZ]
    access_method: public_json_endpoint
    endpoint: mock://sse
    license_url: https://example.test/sse-legal
    allows_fetch: true
    allows_store_response: true
    allows_display: true
    allows_redistribute: false
    frequency_limit: daily_once_after_close
    attribution: 数据来源：上海证券交易所
    license_reviewed_at: '2026-10-05'
    conclusion: accepted
  - provider_id: vendor-independent
    provider_name: 合成独立提供方
    provider_kind: independent_api
    module: market_indices
    symbols: [000001.SH, 399001.SZ, 399006.SZ]
    access_method: public_json_endpoint
    endpoint: mock://vendor
    license_url: https://example.test/vendor-legal
    allows_fetch: true
    allows_store_response: true
    allows_display: true
    allows_redistribute: false
    frequency_limit: daily_once_after_close
    attribution: 数据来源：合成独立提供方
    license_reviewed_at: '2026-10-05'
    conclusion: accepted
  - provider_id: vendor-official-candidates
    provider_name: 合成官方来源
    provider_kind: exchange_official
    module: policy_regulation
    symbols: []
    access_method: public_json_endpoint
    endpoint: fixture://policy
    license_url: https://example.test/policy-legal
    allows_fetch: true
    allows_store_response: true
    allows_display: true
    allows_redistribute: false
    frequency_limit: daily_once_after_close
    attribution: 数据来源：合成官方来源
    license_reviewed_at: '2026-10-05'
    conclusion: accepted
""",
        encoding="utf-8",
    )
    return load_source_registry(path)


def test_collect_real_marks_failed_official_check_as_failed_coverage(tmp_path):
    store = _store(tmp_path)
    config = _config(tmp_path)

    class FailingOfficialClient(StaticOfficialClient):
        def get(self, url: str, timeout: int = 15):
            raise _FakeHTTPError("模拟官方来源不可达")

    result = collect_real_after_close(
        request=_request("run-official-failed"),
        config=config,
        store=store,
        registry=_dual_sourced_registry(tmp_path),
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
            MarketDataCollector(client=FakeIndexClient("vendor", "3021.45")),
        ),
        official_collector=OfficialSourceCollector(
            client=FailingOfficialClient(),
            targets=[
                OfficialSourceTarget(
                    module="policy_regulation",
                    source_name="不可达交易所",
                    source_url="fixture://policy",
                    source_type=SourceType.EXCHANGE,
                )
            ],
        ),
    )

    coverage = {
        item.source_name: item
        for item in store.list_module_coverage("run-official-failed")
        if item.source_name == "不可达交易所"
    }
    assert coverage["不可达交易所"].status == ModuleCoverageStatus.FAILED
    assert result.status == RunStatus.RUNNING
    assert any("不可达交易所" in warning_id for warning_id in result.warning_codes)


def test_collect_real_marks_contentless_official_source_as_no_updates(tmp_path):
    store = _store(tmp_path)
    config = _config(tmp_path)

    class EmptyOfficialClient(StaticOfficialClient):
        HTML = "<html><head></head><body><div>导航</div></body></html>"

    collect_real_after_close(
        request=_request("run-official-empty"),
        config=config,
        store=store,
        registry=_dual_sourced_registry(tmp_path),
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
            MarketDataCollector(client=FakeIndexClient("vendor", "3021.45")),
        ),
        official_collector=OfficialSourceCollector(
            client=EmptyOfficialClient(),
            targets=[
                OfficialSourceTarget(
                    module="policy_regulation",
                    source_name="静默交易所",
                    source_url="fixture://policy",
                    source_type=SourceType.EXCHANGE,
                )
            ],
        ),
    )

    coverage = {
        item.source_name: item
        for item in store.list_module_coverage("run-official-empty")
        if item.source_name == "静默交易所"
    }
    assert coverage["静默交易所"].status == ModuleCoverageStatus.NO_UPDATES


class _FakeHTTPError(httpx.HTTPError):
    """官方采集器按 httpx.HTTPError 分支降级为 check_failed。"""
