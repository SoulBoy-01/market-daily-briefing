from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from market_briefing.domain import ReportType


@dataclass(frozen=True)
class AppConfig:
    database_path: Path
    raw_dir: Path
    reports_dir: Path
    generation_provider: str
    report_modules: dict[ReportType, dict[str, bool]]

    def enabled_modules(self, report_type: ReportType) -> list[str]:
        modules = self.report_modules.get(report_type, {})
        return [name for name, enabled in modules.items() if enabled]


def load_config(path: Path) -> AppConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    app_payload: dict[str, Any] = payload["app"]
    generation_payload: dict[str, Any] = payload.get("generation", {})
    report_types_payload: dict[str, Any] = payload.get("report_types", {})

    report_modules: dict[ReportType, dict[str, bool]] = {}
    for report_type in ReportType:
        modules_payload = report_types_payload.get(report_type.value, {}).get("modules", {})
        report_modules[report_type] = {
            str(name): bool(enabled) for name, enabled in modules_payload.items()
        }

    return AppConfig(
        database_path=Path(app_payload["database_path"]),
        raw_dir=Path(app_payload["raw_dir"]),
        reports_dir=Path(app_payload["reports_dir"]),
        generation_provider=str(generation_payload.get("provider", "template")),
        report_modules=report_modules,
    )
