from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class SourceRegistryError(ValueError):
    pass


PROVIDER_KINDS = frozenset({"exchange_official", "independent_api"})

REQUIRED_FIELDS = (
    "provider_id",
    "provider_name",
    "provider_kind",
    "module",
    "symbols",
    "access_method",
    "endpoint",
    "license_url",
    "frequency_limit",
    "attribution",
    "license_reviewed_at",
    "conclusion",
)


@dataclass(frozen=True)
class ApprovedSource:
    """已批准来源：许可审查完成并获准用于指定运行模式的数据来源。"""

    provider_id: str
    provider_name: str
    provider_kind: str
    module: str
    symbols: tuple[str, ...]
    access_method: str
    endpoint: str
    license_url: str
    allows_fetch: bool
    allows_store_response: bool
    allows_display: bool
    allows_redistribute: bool
    frequency_limit: str
    attribution: str
    license_reviewed_at: str
    conclusion: str


@dataclass(frozen=True)
class SourceRegistry:
    sources: tuple[ApprovedSource, ...]

    def providers_for_symbol(self, symbol: str) -> tuple[ApprovedSource, ...]:
        return tuple(source for source in self.sources if symbol in source.symbols)


def load_source_registry(path: Path) -> SourceRegistry:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_sources = (payload or {}).get("sources") or []
    sources = tuple(_approved_source(entry) for entry in raw_sources)
    seen: set[str] = set()
    for source in sources:
        if source.provider_id in seen:
            raise SourceRegistryError(f"duplicate provider_id: {source.provider_id}")
        seen.add(source.provider_id)
    return SourceRegistry(sources=sources)


def require_dual_sourced_symbols(
    registry: SourceRegistry,
    symbols: tuple[str, ...],
) -> dict[str, tuple[ApprovedSource, ApprovedSource]]:
    """每个核心指数必须有交易所官方来源与独立 API 服务各一条，且提供方不同。"""
    resolved: dict[str, tuple[ApprovedSource, ApprovedSource]] = {}
    unresolved: list[str] = []
    for symbol in symbols:
        providers = registry.providers_for_symbol(symbol)
        official = next(
            (source for source in providers if source.provider_kind == "exchange_official"),
            None,
        )
        independent = next(
            (
                source
                for source in providers
                if source.provider_kind == "independent_api"
                and source.provider_id != (official.provider_id if official else "")
            ),
            None,
        )
        if official is None or independent is None:
            missing = []
            if official is None:
                missing.append("exchange_official")
            if independent is None:
                missing.append("independent_api")
            unresolved.append(f"{symbol} 缺少 {'/'.join(missing)}")
            continue
        resolved[symbol] = (official, independent)
    if unresolved:
        raise SourceRegistryError(
            "真实模式未解锁，以下核心指数未获得相互独立的已批准双来源："
            + "；".join(unresolved)
        )
    return resolved


def _approved_source(entry: dict[str, Any]) -> ApprovedSource:
    for field in REQUIRED_FIELDS:
        if entry.get(field) in (None, "", []):
            raise SourceRegistryError(
                f"source entry missing required field {field}: {entry.get('provider_id')}"
            )
    provider_kind = str(entry["provider_kind"])
    if provider_kind not in PROVIDER_KINDS:
        raise SourceRegistryError(
            f"unknown provider_kind {provider_kind}: {entry['provider_id']}"
        )
    allows_store_response = _require_bool(entry, "allows_store_response", entry["provider_id"])
    if not allows_store_response:
        raise SourceRegistryError(
            "allows_store_response must be true for an approved source "
            f"(ADR 0004 需要保存原始响应): {entry['provider_id']}"
        )
    for flag in ("allows_fetch", "allows_display"):
        _require_bool(entry, flag, entry["provider_id"])
    return ApprovedSource(
        provider_id=str(entry["provider_id"]),
        provider_name=str(entry["provider_name"]),
        provider_kind=provider_kind,
        module=str(entry["module"]),
        symbols=tuple(str(symbol) for symbol in entry["symbols"]),
        access_method=str(entry["access_method"]),
        endpoint=str(entry["endpoint"]),
        license_url=str(entry["license_url"]),
        allows_fetch=_require_bool(entry, "allows_fetch", entry["provider_id"]),
        allows_store_response=allows_store_response,
        allows_display=_require_bool(entry, "allows_display", entry["provider_id"]),
        allows_redistribute=_require_bool(entry, "allows_redistribute", entry["provider_id"]),
        frequency_limit=str(entry["frequency_limit"]),
        attribution=str(entry["attribution"]),
        license_reviewed_at=str(entry["license_reviewed_at"]),
        conclusion=str(entry["conclusion"]),
    )


def _require_bool(entry: dict[str, Any], field: str, provider_id: str) -> bool:
    if field not in entry or not isinstance(entry[field], bool):
        raise SourceRegistryError(f"{field} must be a boolean for {provider_id}")
    return bool(entry[field])
