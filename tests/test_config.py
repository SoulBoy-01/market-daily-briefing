from pathlib import Path

from market_briefing.config import load_config
from market_briefing.domain import ReportType


def test_load_default_config_contains_storage_paths_and_modules():
    config = load_config(Path("configs/default.yaml"))

    assert config.database_path == Path("data/market_briefing.sqlite")
    assert config.raw_dir == Path("data/raw")
    assert config.effective_staging_dir == Path("data/staging")
    assert config.effective_diagnostics_dir == Path("data/diagnostics")
    assert config.reports_dir == Path("reports")
    assert config.generation_provider == "template"
    assert config.enabled_modules(ReportType.AFTER_CLOSE) == [
        "market_indices",
        "market_temperature",
        "sector_moves",
        "policy_regulation",
        "major_news",
        "risk_points",
    ]
    assert config.enabled_modules(ReportType.PRE_OPEN_UPDATE) == [
        "overnight_context",
        "policy_news_delta",
        "today_watchpoints",
    ]


def test_module_can_be_disabled_in_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
app:
  database_path: data/test.sqlite
  raw_dir: data/raw
  staging_dir: data/custom-staging
  diagnostics_dir: data/custom-diagnostics
  reports_dir: reports
generation:
  provider: template
report_types:
  after_close:
    modules:
      market_indices: true
      risk_points: false
  pre_open_update:
    modules:
      overnight_context: true
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.enabled_modules(ReportType.AFTER_CLOSE) == ["market_indices"]
    assert config.enabled_modules(ReportType.PRE_OPEN_UPDATE) == ["overnight_context"]
    assert config.effective_staging_dir == Path("data/custom-staging")
    assert config.effective_diagnostics_dir == Path("data/custom-diagnostics")
