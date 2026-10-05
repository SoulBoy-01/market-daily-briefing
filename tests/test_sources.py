from pathlib import Path

import pytest

from market_briefing.sources import (
    ApprovedSource,
    SourceRegistryError,
    load_source_registry,
    require_dual_sourced_symbols,
)


def _registry_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(body, encoding="utf-8")
    return path


VALID_ENTRY = """
  - provider_id: sse-official
    provider_name: 上海证券交易所
    provider_kind: exchange_official
    module: market_indices
    symbols:
      - 000001.SH
    access_method: public_json_endpoint
    endpoint: https://query.sse.com.cn/commonQuery.do
    license_url: https://www.sse.com.cn/home/legal/
    allows_fetch: true
    allows_store_response: true
    allows_display: true
    allows_redistribute: false
    frequency_limit: daily_once_after_close
    attribution: 数据来源：上海证券交易所
    license_reviewed_at: '2026-10-05'
    conclusion: accepted_for_non_commercial_local_use
"""


def test_load_registry_reads_approved_source_fields(tmp_path):
    registry = load_source_registry(_registry_file(tmp_path, f"sources:{VALID_ENTRY}"))

    assert len(registry.sources) == 1
    source = registry.sources[0]
    assert source.provider_id == "sse-official"
    assert source.provider_name == "上海证券交易所"
    assert source.provider_kind == "exchange_official"
    assert source.symbols == ("000001.SH",)
    assert source.allows_store_response is True
    assert source.allows_redistribute is False
    assert source.license_reviewed_at == "2026-10-05"


def test_load_registry_rejects_source_without_license_review(tmp_path):
    body = VALID_ENTRY.replace("    license_reviewed_at: '2026-10-05'\n", "")

    with pytest.raises(SourceRegistryError, match="license_reviewed_at"):
        load_source_registry(_registry_file(tmp_path, f"sources:{body}"))


def test_load_registry_rejects_source_that_forbids_response_storage(tmp_path):
    body = VALID_ENTRY.replace("allows_store_response: true", "allows_store_response: false")

    with pytest.raises(SourceRegistryError, match="allows_store_response"):
        load_source_registry(_registry_file(tmp_path, f"sources:{body}"))


def test_load_registry_rejects_unknown_provider_kind(tmp_path):
    body = VALID_ENTRY.replace(
        "provider_kind: exchange_official",
        "provider_kind: scraped_webpage",
    )

    with pytest.raises(SourceRegistryError, match="provider_kind"):
        load_source_registry(_registry_file(tmp_path, f"sources:{body}"))


def test_load_registry_rejects_duplicate_provider_ids(tmp_path):
    body = VALID_ENTRY + VALID_ENTRY

    with pytest.raises(SourceRegistryError, match="duplicate provider_id"):
        load_source_registry(_registry_file(tmp_path, f"sources:{body}"))


def test_require_dual_sourced_symbols_reports_missing_independent_api(tmp_path):
    registry = load_source_registry(_registry_file(tmp_path, f"sources:{VALID_ENTRY}"))

    with pytest.raises(SourceRegistryError) as excinfo:
        require_dual_sourced_symbols(
            registry,
            ("000001.SH", "399001.SZ", "399006.SZ"),
        )

    message = str(excinfo.value)
    assert "399001.SZ" in message
    assert "399006.SZ" in message
    assert "000001.SH" in message
    assert "independent_api" in message


def test_require_dual_sourced_symbols_accepts_exchange_plus_independent_api(tmp_path):
    official = VALID_ENTRY.replace(
        "      - 000001.SH",
        "      - 000001.SH\n      - 399001.SZ\n      - 399006.SZ",
    )
    independent = official.replace("sse-official", "vendor-independent").replace(
        "provider_kind: exchange_official",
        "provider_kind: independent_api",
    )
    registry = load_source_registry(
        _registry_file(tmp_path, f"sources:{official}{independent}")
    )

    resolved = require_dual_sourced_symbols(
        registry,
        ("000001.SH", "399001.SZ", "399006.SZ"),
    )

    assert set(resolved) == {"000001.SH", "399001.SZ", "399006.SZ"}
    assert resolved["000001.SH"][0].provider_id == "sse-official"
    assert resolved["000001.SH"][1].provider_id == "vendor-independent"
    assert all(len(providers) == 2 for providers in resolved.values())


def test_require_dual_sourced_symbols_rejects_same_provider_on_both_legs(tmp_path):
    both_legs = VALID_ENTRY.replace(
        "provider_kind: exchange_official",
        "provider_kind: exchange_official",
    ) + VALID_ENTRY.replace("sse-official", "sse-mirror").replace(
        "provider_kind: exchange_official",
        "provider_kind: independent_api",
    )
    registry = load_source_registry(_registry_file(tmp_path, f"sources:{both_legs}"))

    resolved = require_dual_sourced_symbols(registry, ("000001.SH",))

    assert [source.provider_id for source in resolved["000001.SH"]] == [
        "sse-official",
        "sse-mirror",
    ]


def test_empty_registry_blocks_dual_sourcing(tmp_path):
    registry = load_source_registry(_registry_file(tmp_path, "sources: []"))

    with pytest.raises(SourceRegistryError, match="independent_api"):
        require_dual_sourced_symbols(registry, ("000001.SH",))


def test_registry_source_is_immutable():
    source = ApprovedSource(
        provider_id="p",
        provider_name="提供方",
        provider_kind="exchange_official",
        module="market_indices",
        symbols=("000001.SH",),
        access_method="public_json_endpoint",
        endpoint="https://example.test/api",
        license_url="https://example.test/legal",
        allows_fetch=True,
        allows_store_response=True,
        allows_display=True,
        allows_redistribute=False,
        frequency_limit="daily_once_after_close",
        attribution="数据来源：提供方",
        license_reviewed_at="2026-10-05",
        conclusion="accepted_for_non_commercial_local_use",
    )

    with pytest.raises(Exception):
        source.provider_id = "other"
