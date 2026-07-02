import json
from pathlib import Path

from market_briefing.collectors.fixtures import FixtureCollector
from market_briefing.domain import FactClassification, ReportType, SourceType


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
    assert Path(result.snapshots[0].raw_path).exists()
    assert json.loads(Path(result.snapshots[0].raw_path).read_text(encoding="utf-8")) == {
        "indices": [
            {"name": "Shanghai Composite", "change_pct": 0.52, "close": 3021.45},
            {"name": "Shenzhen Component", "change_pct": 0.31, "close": 9450.12},
        ]
    }
    assert result.facts[0].fact_id == "fact-market-001"
    assert result.facts[0].run_id == "run-fixture-001"
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
