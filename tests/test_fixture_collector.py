import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from market_briefing.audit import verify_snapshot_hash
from market_briefing.collectors.fixtures import FixtureCollector
from market_briefing.domain import FactClassification, ReportType, SourceType


def test_fixture_collector_defaults_fetched_at_to_report_date_midnight(tmp_path):
    collector = FixtureCollector(Path("tests/fixtures/after_close_sources.json"))

    first = collector.collect(
        run_id="run-fixture-default-clock",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "policy_regulation", "risk_points"],
        raw_dir=tmp_path / "raw",
    )
    second = collector.collect(
        run_id="run-fixture-default-clock",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "policy_regulation", "risk_points"],
        raw_dir=tmp_path / "raw",
    )
    expected_fetched_at = datetime.fromisoformat("2026-07-02T00:00:00+00:00")

    assert {snapshot.fetched_at for snapshot in first.snapshots} == {expected_fetched_at}
    assert {fact.fetched_at for fact in first.facts} == {expected_fetched_at}
    assert [snapshot.fetched_at for snapshot in first.snapshots] == [
        snapshot.fetched_at for snapshot in second.snapshots
    ]
    assert [fact.fetched_at for fact in first.facts] == [
        fact.fetched_at for fact in second.facts
    ]


def test_fixture_collector_uses_injected_clock_for_fetched_at(tmp_path):
    fetched_at = datetime(2026, 7, 2, 7, 30, tzinfo=timezone.utc)
    default_fetched_at = datetime.fromisoformat("2026-07-02T00:00:00+00:00")
    collector = FixtureCollector(
        Path("tests/fixtures/after_close_sources.json"),
        clock=lambda: fetched_at,
    )

    first = collector.collect(
        run_id="run-fixture-clock-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "policy_regulation", "risk_points"],
        raw_dir=tmp_path / "first-raw",
    )
    second = collector.collect(
        run_id="run-fixture-clock-002",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "policy_regulation", "risk_points"],
        raw_dir=tmp_path / "second-raw",
    )

    assert fetched_at != default_fetched_at
    assert {snapshot.fetched_at for snapshot in first.snapshots} == {fetched_at}
    assert {fact.fetched_at for fact in first.facts} == {fetched_at}
    assert [snapshot.fetched_at for snapshot in first.snapshots] == [
        snapshot.fetched_at for snapshot in second.snapshots
    ]
    assert [fact.fetched_at for fact in first.facts] == [
        fact.fetched_at for fact in second.facts
    ]


def test_fixture_collector_writes_raw_snapshots_and_facts(tmp_path):
    collector = FixtureCollector(Path("tests/fixtures/after_close_sources.json"))

    result = collector.collect(
        run_id="run-fixture-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices", "policy_regulation", "risk_points"],
        raw_dir=tmp_path / "raw",
    )

    assert len(result.snapshots) == 3
    assert len(result.facts) == 4
    assert result.snapshots[0].source_type == SourceType.DATA_API
    assert result.snapshots[0].metadata["fact_count"] == 2
    assert result.snapshots[0].metadata["fixture_path"] == "tests/fixtures/after_close_sources.json"
    assert verify_snapshot_hash(
        Path(result.snapshots[0].raw_path), result.snapshots[0].content_sha256
    )
    assert result.snapshots[0].provider_name == "Fixture Market Data"
    assert result.snapshots[0].license_ref == "fixture:test-data"
    assert Path(result.snapshots[0].raw_path).exists()
    assert Path(result.snapshots[0].raw_path).name == "001-market_indices.json"
    assert json.loads(Path(result.snapshots[0].raw_path).read_text(encoding="utf-8")) == {
        "indices": [
            {"name": "Shanghai Composite", "change_pct": 0.52, "close": 3021.45},
            {"name": "Shenzhen Component", "change_pct": 0.31, "close": 9450.12},
        ]
    }
    policy_snapshot = result.snapshots[1]
    assert policy_snapshot.module == "policy_regulation"
    assert Path(policy_snapshot.raw_path).name == "002-policy_regulation.html"
    assert (
        Path(policy_snapshot.raw_path).read_text(encoding="utf-8")
        == "<article><h1>Regulatory update</h1><p>The exchange published a market supervision bulletin.</p></article>"
    )
    assert result.facts[0].fact_id == "fact-market-001"
    assert result.facts[0].run_id == "run-fixture-001"
    assert result.facts[0].report_date == "2026-07-02"
    assert result.facts[0].report_type == ReportType.AFTER_CLOSE
    assert result.facts[0].source_name == "Fixture Market Data"
    assert result.facts[0].source_url == "fixture://market/indices"
    assert result.facts[0].source_type == SourceType.DATA_API
    assert result.facts[0].confidence == "high"
    assert result.facts[0].raw_snapshot_path == result.snapshots[0].raw_path
    assert Path(result.facts[0].raw_snapshot_path).exists()
    assert result.facts[-1].classification == FactClassification.INFERENCE
    assert result.facts[-1].derived_from_fact_ids == ("fact-market-001", "fact-policy-001")
    assert result.facts[-1].used_in_sections == ("risk_points",)


def test_fixture_collector_respects_enabled_modules(tmp_path):
    collector = FixtureCollector(Path("tests/fixtures/after_close_sources.json"))

    result = collector.collect(
        run_id="run-fixture-002",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
        raw_dir=tmp_path / "raw",
    )

    assert [snapshot.module for snapshot in result.snapshots] == ["market_indices"]
    assert [fact.module for fact in result.facts] == ["market_indices", "market_indices"]
    assert len(list((tmp_path / "raw" / "2026-07-02" / "run-fixture-002").iterdir())) == 1


def test_fixture_collector_collects_pre_open_fixture(tmp_path):
    collector = FixtureCollector(Path("tests/fixtures/pre_open_sources.json"))

    result = collector.collect(
        run_id="run-fixture-003",
        report_date="2026-07-03",
        report_type=ReportType.PRE_OPEN_UPDATE,
        enabled_modules=["overnight_context", "today_watchpoints"],
        raw_dir=tmp_path / "raw",
    )

    assert [snapshot.module for snapshot in result.snapshots] == [
        "overnight_context",
        "today_watchpoints",
    ]
    assert [Path(snapshot.raw_path).name for snapshot in result.snapshots] == [
        "001-overnight_context.json",
        "002-today_watchpoints.json",
    ]
    assert [fact.fact_id for fact in result.facts] == ["fact-overnight-001", "fact-watch-001"]
    assert result.facts[0].report_date == "2026-07-03"
    assert result.facts[0].report_type == ReportType.PRE_OPEN_UPDATE
    assert result.facts[1].classification == FactClassification.INFERENCE
    assert result.facts[1].derived_from_fact_ids == ("fact-overnight-001",)


def test_fixture_collector_keeps_raw_paths_unique_for_same_module_sources(tmp_path):
    fixture_path = tmp_path / "duplicate_module_sources.json"
    fixture_path.write_text(
        json.dumps(
            {
                "report_date": "2026-07-02",
                "report_type": "after_close",
                "sources": [
                    {
                        "module": "market_indices",
                        "source_name": "Fixture Market Data A",
                        "source_url": "fixture://market/indices/a",
                        "source_type": "data_api",
                        "published_at": "2026-07-02T15:05:00+08:00",
                        "content_type": "application/json",
                        "content": {"label": "first"},
                        "facts": [
                            {
                                "fact_id": "fact-duplicate-001",
                                "claim": "First duplicate-module source.",
                                "classification": "fact",
                                "confidence": "high",
                                "used_in_sections": ["market_indices"],
                            }
                        ],
                    },
                    {
                        "module": "market_indices",
                        "source_name": "Fixture Market Data B",
                        "source_url": "fixture://market/indices/b",
                        "source_type": "data_api",
                        "published_at": "2026-07-02T15:06:00+08:00",
                        "content_type": "application/json",
                        "content": {"label": "second"},
                        "facts": [
                            {
                                "fact_id": "fact-duplicate-002",
                                "claim": "Second duplicate-module source.",
                                "classification": "fact",
                                "confidence": "high",
                                "used_in_sections": ["market_indices"],
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    collector = FixtureCollector(fixture_path)

    result = collector.collect(
        run_id="run-fixture-004",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
        raw_dir=tmp_path / "raw",
    )

    raw_paths = [Path(snapshot.raw_path) for snapshot in result.snapshots]
    assert [raw_path.name for raw_path in raw_paths] == [
        "001-market_indices.json",
        "002-market_indices.json",
    ]
    assert len(set(raw_paths)) == 2
    assert all(raw_path.exists() for raw_path in raw_paths)
    assert json.loads(raw_paths[0].read_text(encoding="utf-8")) == {"label": "first"}
    assert json.loads(raw_paths[1].read_text(encoding="utf-8")) == {"label": "second"}
    assert [fact.raw_snapshot_path for fact in result.facts] == [
        str(raw_paths[0]),
        str(raw_paths[1]),
    ]


def test_fixture_collector_rejects_unsupported_content_type(tmp_path):
    fixture_path = tmp_path / "unsupported_content_type_sources.json"
    fixture_path.write_text(
        json.dumps(
            {
                "report_date": "2026-07-02",
                "report_type": "after_close",
                "sources": [
                    {
                        "module": "market_indices",
                        "source_name": "Fixture Unsupported Source",
                        "source_url": "fixture://market/unsupported",
                        "source_type": "other",
                        "published_at": "2026-07-02T15:05:00+08:00",
                        "content_type": "text/plain",
                        "content": "plain text is not a supported raw fixture type",
                        "facts": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    collector = FixtureCollector(fixture_path)

    with pytest.raises(ValueError, match="Unsupported fixture content type: text/plain"):
        collector.collect(
            run_id="run-fixture-unsupported",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            enabled_modules=["market_indices"],
            raw_dir=tmp_path / "raw",
        )
