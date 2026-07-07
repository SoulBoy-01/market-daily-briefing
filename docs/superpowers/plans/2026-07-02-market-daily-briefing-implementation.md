# Market Daily Briefing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local A-share daily briefing MVP that can generate auditable post-close and pre-open reports, expose them in a Loop First dashboard, and preserve feedback for the next run.

**Architecture:** Use a Python package with a small FastAPI/Jinja dashboard. Keep the audit core independent from the web layer: collectors create snapshots, normalizers create atomic facts, report generation consumes only facts, and the dashboard reads persisted runs/reports/feedback from SQLite and files.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, sqlite3, pytest, httpx, BeautifulSoup4, markdown-it-py, optional AkShare adapter.

---

## File Structure

Create this structure during implementation:

```text
.
|-- .gitignore
|-- README.md
|-- pyproject.toml
|-- configs/
|   `-- default.yaml
|-- data/
|   `-- .gitkeep
|-- reports/
|   `-- .gitkeep
|-- src/
|   `-- market_briefing/
|       |-- __init__.py
|       |-- app.py
|       |-- config.py
|       |-- domain.py
|       |-- feedback.py
|       |-- llm.py
|       |-- pipeline.py
|       |-- reporting.py
|       |-- storage.py
|       |-- validation.py
|       |-- collectors/
|       |   |-- __init__.py
|       |   |-- base.py
|       |   |-- fixtures.py
|       |   |-- market_data.py
|       |   `-- official_sources.py
|       |-- static/
|       |   `-- styles.css
|       `-- templates/
|           |-- base.html
|           |-- dashboard.html
|           |-- report.html
|           `-- run.html
`-- tests/
    |-- conftest.py
    |-- fixtures/
    |   |-- after_close_sources.json
    |   `-- pre_open_sources.json
    |-- test_config.py
    |-- test_domain.py
    |-- test_feedback.py
    |-- test_pipeline.py
    |-- test_reporting.py
    |-- test_storage.py
    |-- test_validation.py
    `-- test_web.py
```

Responsibility map:

- `domain.py`: enums and dataclasses shared across the system.
- `config.py`: load module/source/provider settings from YAML and environment variables.
- `storage.py`: SQLite schema, repositories, and file path helpers.
- `collectors/`: convert external or fixture inputs into raw snapshots.
- `pipeline.py`: orchestrate runs from snapshots to facts to reports.
- `reporting.py`: template-based Markdown/HTML generation from facts.
- `validation.py`: enforce fact-id citations and no unsupported claims.
- `feedback.py`: store section feedback and summarize it for the next run.
- `llm.py`: provider interface plus template/no-op default and mockable OpenAI-compatible provider boundary.
- `app.py`: FastAPI routes and dashboard rendering only.

## Task 1: Project Skeleton and Test Harness

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `configs/default.yaml`
- Create: `src/market_briefing/__init__.py`
- Create: `tests/test_project_sanity.py`

- [ ] **Step 1: Initialize git if the directory is not already a repository**

Run:

```powershell
git rev-parse --is-inside-work-tree
```

Expected if not initialized:

```text
fatal: not a git repository (or any of the parent directories): .git
```

If not initialized, run:

```powershell
git init
```

Expected:

```text
Initialized empty Git repository
```

- [ ] **Step 2: Write the failing sanity test**

Create `tests/test_project_sanity.py`:

```python
import market_briefing


def test_package_version_is_defined():
    assert market_briefing.__version__ == "0.1.0"
```

- [ ] **Step 3: Run the sanity test to verify it fails before package setup**

Run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install pytest
.\.venv\Scripts\python -m pytest tests/test_project_sanity.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'market_briefing'
```

- [ ] **Step 4: Create package metadata and the initial package**

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.superpowers/
data/*
!data/.gitkeep
reports/*
!reports/.gitkeep
*.sqlite
*.sqlite3
.env
```

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "market-daily-briefing"
version = "0.1.0"
description = "Auditable A-share daily market briefing MVP"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "jinja2>=3.1",
  "python-multipart>=0.0.9",
  "pydantic>=2.8",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "beautifulsoup4>=4.12",
  "markdown-it-py>=3.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "pytest-cov>=5.0",
  "ruff>=0.5",
]
sources = [
  "akshare>=1.14",
  "pandas>=2.2",
]

[project.scripts]
market-briefing = "market_briefing.pipeline:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
market_briefing = ["templates/*.html", "static/*.css"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

Create `src/market_briefing/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `configs/default.yaml`:

```yaml
app:
  database_path: data/market_briefing.sqlite
  raw_dir: data/raw
  reports_dir: reports
  default_report_date_timezone: Asia/Shanghai

generation:
  provider: template
  openai_compatible:
    base_url_env: OPENAI_BASE_URL
    api_key_env: OPENAI_API_KEY
    model_env: OPENAI_MODEL

report_types:
  after_close:
    modules:
      market_indices: true
      market_temperature: true
      sector_moves: true
      policy_regulation: true
      major_news: true
      risk_points: true
  pre_open_update:
    modules:
      overnight_context: true
      policy_news_delta: true
      today_watchpoints: true
```

Create `data/.gitkeep` and `reports/.gitkeep` as empty files.

- [ ] **Step 5: Run the sanity test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest tests/test_project_sanity.py -v
```

Expected:

```text
tests/test_project_sanity.py::test_package_version_is_defined PASSED
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add .gitignore README.md pyproject.toml configs/default.yaml data/.gitkeep reports/.gitkeep src/market_briefing/__init__.py tests/test_project_sanity.py
git commit -m "chore: initialize market briefing project"
```

## Task 2: Domain Model

**Files:**
- Create: `src/market_briefing/domain.py`
- Create: `tests/test_domain.py`

- [ ] **Step 1: Write failing tests for run, snapshot, fact, report, and feedback models**

Create `tests/test_domain.py`:

```python
from datetime import datetime, timezone

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    FeedbackEntry,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    SourceType,
)


def test_atomic_fact_requires_supported_classification_and_can_be_serialized():
    fact = AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="上证指数收涨 0.5%。",
        classification=FactClassification.FACT,
        source_name="Fixture Market Data",
        source_url="fixture://market/indices",
        source_type=SourceType.DATA_API,
        published_at=datetime(2026, 7, 2, 15, 5, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 7, 2, 15, 10, tzinfo=timezone.utc),
        confidence="high",
        raw_snapshot_path="data/raw/2026-07-02/run-001/indices.json",
        derived_from_fact_ids=[],
        used_in_sections=["market_indices"],
    )

    payload = fact.to_record()

    assert payload["fact_id"] == "fact-001"
    assert payload["classification"] == "fact"
    assert payload["report_type"] == "after_close"
    assert payload["source_type"] == "data_api"


def test_report_collects_all_fact_ids_from_sections():
    section = ReportSection(
        section_id="market_indices",
        title="指数表现",
        body="上证指数收涨。[fact-001]",
        fact_ids=["fact-001"],
        status="ok",
    )
    report = Report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="A股盘后简报",
        sections=[section],
        markdown_path="reports/2026-07-02/after_close/briefing.md",
        html_path="reports/2026-07-02/after_close/briefing.html",
        fact_ledger_path="reports/2026-07-02/after_close/fact_ledger.json",
    )

    assert report.all_fact_ids() == {"fact-001"}


def test_feedback_entry_summarizes_tags_and_note():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk", "unclear_citation"],
        note="风险点要更明确引用事实。",
        created_at=datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc),
    )

    assert entry.summary_line() == "risk_points: score=4; tags=insufficient_risk,unclear_citation; note=风险点要更明确引用事实。"


def test_run_defaults_to_created_status_and_tracks_modules():
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.PRE_OPEN_UPDATE,
        enabled_modules=["overnight_context", "today_watchpoints"],
    )

    assert run.status == RunStatus.CREATED
    assert run.enabled_modules == ("overnight_context", "today_watchpoints")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_domain.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.domain'
```

- [ ] **Step 3: Implement the domain model**

Create `src/market_briefing/domain.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ReportType(StrEnum):
    AFTER_CLOSE = "after_close"
    PRE_OPEN_UPDATE = "pre_open_update"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class FactClassification(StrEnum):
    FACT = "fact"
    OPINION = "opinion"
    INFERENCE = "inference"
    UNVERIFIED = "unverified"


class SourceType(StrEnum):
    OFFICIAL = "official"
    EXCHANGE = "exchange"
    MEDIA = "media"
    DATA_API = "data_api"
    OTHER = "other"


@dataclass(frozen=True)
class RawSnapshot:
    snapshot_id: str
    run_id: str
    module: str
    source_name: str
    source_url: str
    source_type: SourceType
    fetched_at: datetime
    content_type: str
    raw_path: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id,
            "module": self.module,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type.value,
            "fetched_at": self.fetched_at.isoformat(),
            "content_type": self.content_type,
            "raw_path": self.raw_path,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AtomicFact:
    fact_id: str
    run_id: str
    report_date: str
    report_type: ReportType
    module: str
    claim: str
    classification: FactClassification
    source_name: str
    source_url: str
    source_type: SourceType
    published_at: datetime | None
    fetched_at: datetime
    confidence: str
    raw_snapshot_path: str
    derived_from_fact_ids: list[str] = field(default_factory=list)
    used_in_sections: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "run_id": self.run_id,
            "report_date": self.report_date,
            "report_type": self.report_type.value,
            "module": self.module,
            "claim": self.claim,
            "classification": self.classification.value,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type.value,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "fetched_at": self.fetched_at.isoformat(),
            "confidence": self.confidence,
            "raw_snapshot_path": self.raw_snapshot_path,
            "derived_from_fact_ids": list(self.derived_from_fact_ids),
            "used_in_sections": list(self.used_in_sections),
        }


@dataclass(frozen=True)
class ReportSection:
    section_id: str
    title: str
    body: str
    fact_ids: list[str]
    status: str


@dataclass(frozen=True)
class Report:
    report_id: str
    run_id: str
    report_date: str
    report_type: ReportType
    title: str
    sections: list[ReportSection]
    markdown_path: str
    html_path: str
    fact_ledger_path: str

    def all_fact_ids(self) -> set[str]:
        return {fact_id for section in self.sections for fact_id in section.fact_ids}


@dataclass(frozen=True)
class FeedbackEntry:
    feedback_id: str
    report_id: str
    section_id: str
    score: int
    tags: list[str]
    note: str
    created_at: datetime

    def summary_line(self) -> str:
        tag_text = ",".join(self.tags)
        return f"{self.section_id}: score={self.score}; tags={tag_text}; note={self.note}"


@dataclass(frozen=True)
class Run:
    run_id: str
    report_date: str
    report_type: ReportType
    enabled_modules: list[str]
    status: RunStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    warning_count: int = 0
    error_message: str | None = None

    @classmethod
    def create(cls, run_id: str, report_date: str, report_type: ReportType, enabled_modules: list[str]) -> "Run":
        return cls(
            run_id=run_id,
            report_date=report_date,
            report_type=report_type,
            enabled_modules=enabled_modules,
            status=RunStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
```

- [ ] **Step 4: Run domain tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_domain.py -v
```

Expected:

```text
tests/test_domain.py::test_atomic_fact_requires_supported_classification_and_can_be_serialized PASSED
tests/test_domain.py::test_report_collects_all_fact_ids_from_sections PASSED
tests/test_domain.py::test_feedback_entry_summarizes_tags_and_note PASSED
tests/test_domain.py::test_run_defaults_to_created_status_and_tracks_modules PASSED
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/market_briefing/domain.py tests/test_domain.py
git commit -m "feat: add audit domain model"
```

## Task 3: Configuration Loader

Implementation note after Task 2 review: domain sequence fields are tuple-backed for immutability. New tests should compare tuple values on domain objects, or call `list(...)` when checking JSON/SQLite-facing output.

**Files:**
- Create: `src/market_briefing/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from market_briefing.config import load_config
from market_briefing.domain import ReportType


def test_load_default_config_contains_storage_paths_and_modules():
    config = load_config(Path("configs/default.yaml"))

    assert config.database_path == Path("data/market_briefing.sqlite")
    assert config.raw_dir == Path("data/raw")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_config.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.config'
```

- [ ] **Step 3: Implement the config loader**

Create `src/market_briefing/config.py`:

```python
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
        report_modules[report_type] = {str(name): bool(enabled) for name, enabled in modules_payload.items()}

    return AppConfig(
        database_path=Path(app_payload["database_path"]),
        raw_dir=Path(app_payload["raw_dir"]),
        reports_dir=Path(app_payload["reports_dir"]),
        generation_provider=str(generation_payload.get("provider", "template")),
        report_modules=report_modules,
    )
```

- [ ] **Step 4: Run config tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_config.py -v
```

Expected:

```text
tests/test_config.py::test_load_default_config_contains_storage_paths_and_modules PASSED
tests/test_config.py::test_module_can_be_disabled_in_yaml PASSED
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/market_briefing/config.py tests/test_config.py
git commit -m "feat: load briefing configuration"
```

## Task 4: SQLite Storage and File Path Helpers

**Files:**
- Create: `src/market_briefing/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    SourceType,
)
from market_briefing.storage import BriefingStore, build_report_paths


def test_store_initializes_schema_and_round_trips_run(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    run = Run.create(
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        enabled_modules=["market_indices"],
    )

    store.save_run(run)
    loaded = store.get_run("run-001")

    assert loaded is not None
    assert loaded.run_id == "run-001"
    assert loaded.report_type == ReportType.AFTER_CLOSE
    assert loaded.enabled_modules == ("market_indices",)


def test_store_round_trips_snapshot_fact_and_report(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    fetched_at = datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)
    snapshot = RawSnapshot(
        snapshot_id="snapshot-001",
        run_id="run-001",
        module="market_indices",
        source_name="Fixture",
        source_url="fixture://indices",
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path="data/raw/2026-07-02/run-001/indices.json",
        metadata={"rows": 4},
    )
    fact = AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="上证指数收涨。",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://indices",
        source_type=SourceType.DATA_API,
        published_at=fetched_at,
        fetched_at=fetched_at,
        confidence="high",
        raw_snapshot_path=snapshot.raw_path,
        used_in_sections=["market_indices"],
    )
    report = Report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="盘后简报",
        sections=[ReportSection("market_indices", "指数表现", "上证指数收涨。[fact-001]", ["fact-001"], "ok")],
        markdown_path="reports/2026-07-02/after_close/briefing.md",
        html_path="reports/2026-07-02/after_close/briefing.html",
        fact_ledger_path="reports/2026-07-02/after_close/fact_ledger.json",
    )

    store.save_snapshot(snapshot)
    store.save_facts([fact])
    store.save_report(report)

    assert store.list_snapshots("run-001")[0].snapshot_id == "snapshot-001"
    assert store.list_facts("run-001")[0].fact_id == "fact-001"
    assert store.list_facts("run-001")[0].used_in_sections == ("market_indices",)
    assert store.get_report("report-001").title == "盘后简报"


def test_build_report_paths_uses_date_type_and_run_id(tmp_path):
    paths = build_report_paths(
        reports_dir=tmp_path / "reports",
        report_date="2026-07-02",
        report_type=ReportType.PRE_OPEN_UPDATE,
        run_id="run-abc",
    )

    assert paths.report_dir == tmp_path / "reports" / "2026-07-02" / "pre_open_update" / "run-abc"
    assert paths.markdown_path.name == "briefing.md"
    assert paths.html_path.name == "briefing.html"
    assert paths.fact_ledger_path.name == "fact_ledger.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_storage.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.storage'
```

- [ ] **Step 3: Implement schema and repositories**

Create `src/market_briefing/storage.py` with this public API:

```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    Report,
    ReportSection,
    ReportType,
    Run,
    RunStatus,
    SourceType,
)


@dataclass(frozen=True)
class ReportPaths:
    report_dir: Path
    markdown_path: Path
    html_path: Path
    fact_ledger_path: Path


def build_report_paths(reports_dir: Path, report_date: str, report_type: ReportType, run_id: str) -> ReportPaths:
    report_dir = reports_dir / report_date / report_type.value / run_id
    return ReportPaths(
        report_dir=report_dir,
        markdown_path=report_dir / "briefing.md",
        html_path=report_dir / "briefing.html",
        fact_ledger_path=report_dir / "fact_ledger.json",
    )


class BriefingStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def save_run(self, run: Run) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into runs (
                    run_id, report_date, report_type, enabled_modules, status,
                    created_at, started_at, completed_at, warning_count, error_message
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    enabled_modules=excluded.enabled_modules,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    warning_count=excluded.warning_count,
                    error_message=excluded.error_message
                """,
                (
                    run.run_id,
                    run.report_date,
                    run.report_type.value,
                    json.dumps(run.enabled_modules, ensure_ascii=False),
                    run.status.value,
                    run.created_at.isoformat(),
                    run.started_at.isoformat() if run.started_at else None,
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.warning_count,
                    run.error_message,
                ),
            )

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as connection:
            row = connection.execute("select * from runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            run_id=row["run_id"],
            report_date=row["report_date"],
            report_type=ReportType(row["report_type"]),
            enabled_modules=json.loads(row["enabled_modules"]),
            status=RunStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            warning_count=row["warning_count"],
            error_message=row["error_message"],
        )

    def save_snapshot(self, snapshot: RawSnapshot) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into source_snapshots (
                    snapshot_id, run_id, module, source_name, source_url, source_type,
                    fetched_at, content_type, raw_path, metadata
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.run_id,
                    snapshot.module,
                    snapshot.source_name,
                    snapshot.source_url,
                    snapshot.source_type.value,
                    snapshot.fetched_at.isoformat(),
                    snapshot.content_type,
                    snapshot.raw_path,
                    json.dumps(snapshot.metadata, ensure_ascii=False),
                ),
            )

    def list_snapshots(self, run_id: str) -> list[RawSnapshot]:
        with self.connect() as connection:
            rows = connection.execute(
                "select * from source_snapshots where run_id = ? order by snapshot_id",
                (run_id,),
            ).fetchall()
        return [
            RawSnapshot(
                snapshot_id=row["snapshot_id"],
                run_id=row["run_id"],
                module=row["module"],
                source_name=row["source_name"],
                source_url=row["source_url"],
                source_type=SourceType(row["source_type"]),
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                content_type=row["content_type"],
                raw_path=row["raw_path"],
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def save_facts(self, facts: list[AtomicFact]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                insert into facts (
                    fact_id, run_id, report_date, report_type, module, claim, classification,
                    source_name, source_url, source_type, published_at, fetched_at, confidence,
                    raw_snapshot_path, derived_from_fact_ids, used_in_sections
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fact.fact_id,
                        fact.run_id,
                        fact.report_date,
                        fact.report_type.value,
                        fact.module,
                        fact.claim,
                        fact.classification.value,
                        fact.source_name,
                        fact.source_url,
                        fact.source_type.value,
                        fact.published_at.isoformat() if fact.published_at else None,
                        fact.fetched_at.isoformat(),
                        fact.confidence,
                        fact.raw_snapshot_path,
                        json.dumps(fact.derived_from_fact_ids, ensure_ascii=False),
                        json.dumps(fact.used_in_sections, ensure_ascii=False),
                    )
                    for fact in facts
                ],
            )

    def list_facts(self, run_id: str) -> list[AtomicFact]:
        with self.connect() as connection:
            rows = connection.execute(
                "select * from facts where run_id = ? order by fact_id",
                (run_id,),
            ).fetchall()
        return [
            AtomicFact(
                fact_id=row["fact_id"],
                run_id=row["run_id"],
                report_date=row["report_date"],
                report_type=ReportType(row["report_type"]),
                module=row["module"],
                claim=row["claim"],
                classification=FactClassification(row["classification"]),
                source_name=row["source_name"],
                source_url=row["source_url"],
                source_type=SourceType(row["source_type"]),
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                fetched_at=datetime.fromisoformat(row["fetched_at"]),
                confidence=row["confidence"],
                raw_snapshot_path=row["raw_snapshot_path"],
                derived_from_fact_ids=json.loads(row["derived_from_fact_ids"]),
                used_in_sections=json.loads(row["used_in_sections"]),
            )
            for row in rows
        ]

    def save_report(self, report: Report) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into reports (
                    report_id, run_id, report_date, report_type, title,
                    sections, markdown_path, html_path, fact_ledger_path
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.run_id,
                    report.report_date,
                    report.report_type.value,
                    report.title,
                    json.dumps([section.__dict__ for section in report.sections], ensure_ascii=False),
                    report.markdown_path,
                    report.html_path,
                    report.fact_ledger_path,
                ),
            )

    def get_report(self, report_id: str) -> Report:
        with self.connect() as connection:
            row = connection.execute("select * from reports where report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise KeyError(report_id)
        sections_payload: list[dict[str, Any]] = json.loads(row["sections"])
        return Report(
            report_id=row["report_id"],
            run_id=row["run_id"],
            report_date=row["report_date"],
            report_type=ReportType(row["report_type"]),
            title=row["title"],
            sections=[ReportSection(**section) for section in sections_payload],
            markdown_path=row["markdown_path"],
            html_path=row["html_path"],
            fact_ledger_path=row["fact_ledger_path"],
        )


SCHEMA = """
create table if not exists runs (
    run_id text primary key,
    report_date text not null,
    report_type text not null,
    enabled_modules text not null,
    status text not null,
    created_at text not null,
    started_at text,
    completed_at text,
    warning_count integer not null default 0,
    error_message text
);

create table if not exists source_snapshots (
    snapshot_id text primary key,
    run_id text not null,
    module text not null,
    source_name text not null,
    source_url text not null,
    source_type text not null,
    fetched_at text not null,
    content_type text not null,
    raw_path text not null,
    metadata text not null
);

create table if not exists facts (
    fact_id text primary key,
    run_id text not null,
    report_date text not null,
    report_type text not null,
    module text not null,
    claim text not null,
    classification text not null,
    source_name text not null,
    source_url text not null,
    source_type text not null,
    published_at text,
    fetched_at text not null,
    confidence text not null,
    raw_snapshot_path text not null,
    derived_from_fact_ids text not null,
    used_in_sections text not null
);

create table if not exists reports (
    report_id text primary key,
    run_id text not null,
    report_date text not null,
    report_type text not null,
    title text not null,
    sections text not null,
    markdown_path text not null,
    html_path text not null,
    fact_ledger_path text not null
);
"""
```

- [ ] **Step 4: Run storage tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_storage.py -v
```

Expected:

```text
tests/test_storage.py::test_store_initializes_schema_and_round_trips_run PASSED
tests/test_storage.py::test_store_round_trips_snapshot_fact_and_report PASSED
tests/test_storage.py::test_build_report_paths_uses_date_type_and_run_id PASSED
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/market_briefing/storage.py tests/test_storage.py
git commit -m "feat: persist runs facts snapshots and reports"
```

## Task 5: Fixture Source Collector and Raw Snapshots

**Files:**
- Create: `src/market_briefing/collectors/__init__.py`
- Create: `src/market_briefing/collectors/base.py`
- Create: `src/market_briefing/collectors/fixtures.py`
- Create: `tests/fixtures/after_close_sources.json`
- Create: `tests/fixtures/pre_open_sources.json`
- Create: `tests/test_fixture_collector.py`

- [ ] **Step 1: Write fixture data**

Create `tests/fixtures/after_close_sources.json`:

```json
{
  "report_date": "2026-07-02",
  "report_type": "after_close",
  "sources": [
    {
      "module": "market_indices",
      "source_name": "Fixture Market Data",
      "source_url": "fixture://market/indices",
      "source_type": "data_api",
      "published_at": "2026-07-02T15:05:00+08:00",
      "content_type": "application/json",
      "content": {
        "indices": [
          {"name": "上证指数", "change_pct": 0.52, "close": 3021.45},
          {"name": "深证成指", "change_pct": 0.31, "close": 9450.12}
        ]
      },
      "facts": [
        {
          "fact_id": "fact-market-001",
          "claim": "上证指数收于 3021.45 点，涨幅 0.52%。",
          "classification": "fact",
          "confidence": "high",
          "used_in_sections": ["market_indices"]
        },
        {
          "fact_id": "fact-market-002",
          "claim": "深证成指收于 9450.12 点，涨幅 0.31%。",
          "classification": "fact",
          "confidence": "high",
          "used_in_sections": ["market_indices"]
        }
      ]
    },
    {
      "module": "policy_regulation",
      "source_name": "Fixture Official Source",
      "source_url": "fixture://official/policy",
      "source_type": "official",
      "published_at": "2026-07-02T16:00:00+08:00",
      "content_type": "text/html",
      "content": "<article><h1>监管动态</h1><p>交易所发布市场监管通报。</p></article>",
      "facts": [
        {
          "fact_id": "fact-policy-001",
          "claim": "交易所发布市场监管通报。",
          "classification": "fact",
          "confidence": "high",
          "used_in_sections": ["policy_regulation"]
        }
      ]
    },
    {
      "module": "risk_points",
      "source_name": "System Inference",
      "source_url": "fixture://system/risk",
      "source_type": "other",
      "published_at": "2026-07-02T16:20:00+08:00",
      "content_type": "application/json",
      "content": {"basis": ["fact-market-001", "fact-policy-001"]},
      "facts": [
        {
          "fact_id": "fact-risk-001",
          "claim": "市场风险提示需同时关注指数波动和监管动态。",
          "classification": "inference",
          "confidence": "medium",
          "derived_from_fact_ids": ["fact-market-001", "fact-policy-001"],
          "used_in_sections": ["risk_points"]
        }
      ]
    }
  ]
}
```

Create `tests/fixtures/pre_open_sources.json`:

```json
{
  "report_date": "2026-07-03",
  "report_type": "pre_open_update",
  "sources": [
    {
      "module": "overnight_context",
      "source_name": "Fixture Overnight Data",
      "source_url": "fixture://overnight/global",
      "source_type": "data_api",
      "published_at": "2026-07-03T07:20:00+08:00",
      "content_type": "application/json",
      "content": {"external_context": "隔夜外围市场波动加大。"},
      "facts": [
        {
          "fact_id": "fact-overnight-001",
          "claim": "隔夜外围市场波动加大。",
          "classification": "fact",
          "confidence": "medium",
          "used_in_sections": ["overnight_context"]
        }
      ]
    },
    {
      "module": "today_watchpoints",
      "source_name": "System Inference",
      "source_url": "fixture://system/watchpoints",
      "source_type": "other",
      "published_at": "2026-07-03T08:00:00+08:00",
      "content_type": "application/json",
      "content": {"basis": ["fact-overnight-001"]},
      "facts": [
        {
          "fact_id": "fact-watch-001",
          "claim": "今日需关注外围波动对风险偏好的影响。",
          "classification": "inference",
          "confidence": "medium",
          "derived_from_fact_ids": ["fact-overnight-001"],
          "used_in_sections": ["today_watchpoints"]
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Write failing fixture collector tests**

Create `tests/test_fixture_collector.py`:

```python
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
    assert Path(result.snapshots[0].raw_path).exists()
    assert result.facts[0].fact_id == "fact-market-001"
    assert result.facts[0].run_id == "run-fixture-001"
    assert result.facts[-1].classification == FactClassification.INFERENCE
    assert result.facts[-1].derived_from_fact_ids == ("fact-market-001", "fact-policy-001")


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_fixture_collector.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.collectors'
```

- [ ] **Step 4: Implement collector contracts and fixture collector**

Create `src/market_briefing/collectors/__init__.py`:

```python
"""Source collectors for market briefing inputs."""
```

Create `src/market_briefing/collectors/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from market_briefing.domain import AtomicFact, RawSnapshot


@dataclass(frozen=True)
class CollectionResult:
    snapshots: list[RawSnapshot]
    facts: list[AtomicFact]
```

Create `src/market_briefing/collectors/fixtures.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import (
    AtomicFact,
    FactClassification,
    RawSnapshot,
    ReportType,
    SourceType,
)


class FixtureCollector:
    def __init__(self, fixture_path: Path):
        self.fixture_path = fixture_path

    def collect(
        self,
        run_id: str,
        report_date: str,
        report_type: ReportType,
        enabled_modules: list[str],
        raw_dir: Path,
    ) -> CollectionResult:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        fetched_at = datetime.now(timezone.utc)
        snapshots: list[RawSnapshot] = []
        facts: list[AtomicFact] = []

        for index, source in enumerate(payload["sources"], start=1):
            module = source["module"]
            if module not in enabled_modules:
                continue

            snapshot_id = f"{run_id}-{index:03d}-{module}"
            module_dir = raw_dir / report_date / run_id
            module_dir.mkdir(parents=True, exist_ok=True)
            suffix = "json" if source["content_type"] == "application/json" else "html"
            raw_path = module_dir / f"{module}.{suffix}"
            raw_path.write_text(_render_raw_content(source["content"], source["content_type"]), encoding="utf-8")

            snapshot = RawSnapshot(
                snapshot_id=snapshot_id,
                run_id=run_id,
                module=module,
                source_name=source["source_name"],
                source_url=source["source_url"],
                source_type=SourceType(source["source_type"]),
                fetched_at=fetched_at,
                content_type=source["content_type"],
                raw_path=str(raw_path),
                metadata={"fixture_path": str(self.fixture_path), "fact_count": len(source.get("facts", []))},
            )
            snapshots.append(snapshot)

            published_at = datetime.fromisoformat(source["published_at"])
            for fact_payload in source.get("facts", []):
                facts.append(
                    AtomicFact(
                        fact_id=fact_payload["fact_id"],
                        run_id=run_id,
                        report_date=report_date,
                        report_type=report_type,
                        module=module,
                        claim=fact_payload["claim"],
                        classification=FactClassification(fact_payload["classification"]),
                        source_name=source["source_name"],
                        source_url=source["source_url"],
                        source_type=SourceType(source["source_type"]),
                        published_at=published_at,
                        fetched_at=fetched_at,
                        confidence=fact_payload["confidence"],
                        raw_snapshot_path=str(raw_path),
                        derived_from_fact_ids=fact_payload.get("derived_from_fact_ids", []),
                        used_in_sections=fact_payload.get("used_in_sections", [module]),
                    )
                )

        return CollectionResult(snapshots=snapshots, facts=facts)


def _render_raw_content(content: Any, content_type: str) -> str:
    if content_type == "application/json":
        return json.dumps(content, ensure_ascii=False, indent=2)
    return str(content)
```

- [ ] **Step 5: Run fixture collector tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_fixture_collector.py -v
```

Expected:

```text
tests/test_fixture_collector.py::test_fixture_collector_writes_raw_snapshots_and_facts PASSED
tests/test_fixture_collector.py::test_fixture_collector_respects_enabled_modules PASSED
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/market_briefing/collectors tests/fixtures tests/test_fixture_collector.py
git commit -m "feat: add fixture source collector"
```

## Task 6: Report Validation and Template Rendering

**Files:**
- Create: `src/market_briefing/validation.py`
- Create: `src/market_briefing/reporting.py`
- Create: `tests/test_validation.py`
- Create: `tests/test_reporting.py`

- [ ] **Step 1: Write failing validation tests**

Create `tests/test_validation.py`:

```python
from datetime import datetime, timezone

from market_briefing.domain import AtomicFact, FactClassification, ReportSection, ReportType, SourceType
from market_briefing.validation import validate_report_sections


def _fact(fact_id: str, claim: str) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim=claim,
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        used_in_sections=["market_indices"],
    )


def test_validation_accepts_sections_that_cite_existing_facts():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [ReportSection("market_indices", "指数表现", "上证指数收涨。[fact-001]", ["fact-001"], "ok")]

    result = validate_report_sections(sections, facts)

    assert result.ok is True
    assert result.errors == []


def test_validation_rejects_missing_fact_id():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [ReportSection("market_indices", "指数表现", "引用了不存在事实。[fact-999]", ["fact-999"], "ok")]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert result.errors == ["section market_indices cites missing fact_id fact-999"]


def test_validation_rejects_banned_investment_advice_language():
    facts = [_fact("fact-001", "上证指数收涨。")]
    sections = [ReportSection("risk_points", "风险提示", "建议买入相关个股。[fact-001]", ["fact-001"], "ok")]

    result = validate_report_sections(sections, facts)

    assert result.ok is False
    assert "section risk_points contains banned phrase 建议买入" in result.errors
```

- [ ] **Step 2: Write failing reporting tests**

Create `tests/test_reporting.py`:

```python
from datetime import datetime, timezone

from market_briefing.domain import AtomicFact, FactClassification, ReportType, SourceType
from market_briefing.reporting import build_report, render_html, render_markdown


def _fact(fact_id: str, module: str, claim: str, classification: FactClassification = FactClassification.FACT) -> AtomicFact:
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id=fact_id,
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module=module,
        claim=claim,
        classification=classification,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        derived_from_fact_ids=["fact-001"] if classification == FactClassification.INFERENCE else [],
        used_in_sections=[module],
    )


def test_build_report_groups_facts_by_section_and_marks_inferences():
    facts = [
        _fact("fact-001", "market_indices", "上证指数收涨。"),
        _fact("fact-002", "risk_points", "风险偏好仍需观察。", FactClassification.INFERENCE),
    ]

    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert report.title == "A股盘后简报 2026-07-02"
    assert [section.section_id for section in report.sections] == ["market_indices", "risk_points"]
    assert "推测/归纳" in report.sections[1].body
    assert report.all_fact_ids() == {"fact-001", "fact-002"}


def test_render_markdown_and_html_include_sources_and_fact_ids():
    facts = [_fact("fact-001", "market_indices", "上证指数收涨。")]
    report = build_report(
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=facts,
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    markdown = render_markdown(report, facts)
    html = render_html(markdown)

    assert "# A股盘后简报 2026-07-02" in markdown
    assert "[fact-001]" in markdown
    assert "fixture://source" in markdown
    assert "<h1" in html
    assert "上证指数收涨" in html
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_validation.py tests/test_reporting.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.validation'
```

- [ ] **Step 4: Implement validation**

Create `src/market_briefing/validation.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from market_briefing.domain import AtomicFact, ReportSection


BANNED_PHRASES = ["建议买入", "建议卖出", "目标价", "仓位建议", "应买入", "应卖出"]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]


def validate_report_sections(sections: list[ReportSection], facts: list[AtomicFact]) -> ValidationResult:
    fact_ids = {fact.fact_id for fact in facts}
    errors: list[str] = []

    for section in sections:
        for fact_id in section.fact_ids:
            if fact_id not in fact_ids:
                errors.append(f"section {section.section_id} cites missing fact_id {fact_id}")
        for phrase in BANNED_PHRASES:
            if phrase in section.body:
                errors.append(f"section {section.section_id} contains banned phrase {phrase}")

    return ValidationResult(ok=not errors, errors=errors)
```

- [ ] **Step 5: Implement template report generation**

Create `src/market_briefing/reporting.py`:

```python
from __future__ import annotations

from collections import defaultdict

from markdown_it import MarkdownIt

from market_briefing.domain import AtomicFact, FactClassification, Report, ReportSection, ReportType


SECTION_TITLES = {
    "market_indices": "指数表现",
    "market_temperature": "市场温度",
    "sector_moves": "板块表现",
    "policy_regulation": "政策与监管",
    "major_news": "重大新闻",
    "risk_points": "风险提示",
    "overnight_context": "隔夜环境",
    "policy_news_delta": "政策新闻变化",
    "today_watchpoints": "今日关注点",
}


def build_report(
    report_id: str,
    run_id: str,
    report_date: str,
    report_type: ReportType,
    facts: list[AtomicFact],
    markdown_path: str,
    html_path: str,
    fact_ledger_path: str,
) -> Report:
    grouped: dict[str, list[AtomicFact]] = defaultdict(list)
    for fact in facts:
        for section_id in fact.used_in_sections or [fact.module]:
            grouped[section_id].append(fact)

    sections: list[ReportSection] = []
    for section_id, section_facts in grouped.items():
        body_lines = [_format_fact_line(fact) for fact in section_facts]
        sections.append(
            ReportSection(
                section_id=section_id,
                title=SECTION_TITLES.get(section_id, section_id),
                body="\n".join(body_lines),
                fact_ids=[fact.fact_id for fact in section_facts],
                status="ok",
            )
        )

    title = "A股盘后简报" if report_type == ReportType.AFTER_CLOSE else "A股早盘补充"
    return Report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        title=f"{title} {report_date}",
        sections=sections,
        markdown_path=markdown_path,
        html_path=html_path,
        fact_ledger_path=fact_ledger_path,
    )


def render_markdown(report: Report, facts: list[AtomicFact]) -> str:
    source_lines = [
        f"- [{fact.fact_id}] {fact.source_name}: {fact.source_url} published={fact.published_at.isoformat() if fact.published_at else 'unknown'}"
        for fact in facts
    ]
    section_blocks = [
        f"## {section.title}\n\n{section.body}"
        for section in report.sections
    ]
    return "\n\n".join([f"# {report.title}", *section_blocks, "## 来源索引", "\n".join(source_lines)]) + "\n"


def render_html(markdown: str) -> str:
    body = MarkdownIt("commonmark").render(markdown)
    return f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Market Briefing</title></head><body>{body}</body></html>"


def _format_fact_line(fact: AtomicFact) -> str:
    prefix = {
        FactClassification.FACT: "事实",
        FactClassification.OPINION: "观点",
        FactClassification.INFERENCE: "推测/归纳",
        FactClassification.UNVERIFIED: "待确认",
    }[fact.classification]
    return f"- **{prefix}** {fact.claim} [{fact.fact_id}]"
```

- [ ] **Step 6: Run validation and reporting tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_validation.py tests/test_reporting.py -v
```

Expected:

```text
tests/test_validation.py::test_validation_accepts_sections_that_cite_existing_facts PASSED
tests/test_validation.py::test_validation_rejects_missing_fact_id PASSED
tests/test_validation.py::test_validation_rejects_banned_investment_advice_language PASSED
tests/test_reporting.py::test_build_report_groups_facts_by_section_and_marks_inferences PASSED
tests/test_reporting.py::test_render_markdown_and_html_include_sources_and_fact_ids PASSED
```

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/market_briefing/validation.py src/market_briefing/reporting.py tests/test_validation.py tests/test_reporting.py
git commit -m "feat: render validated template briefings"
```

## Task 7: Feedback Loop Persistence and Summaries

**Files:**
- Create: `src/market_briefing/feedback.py`
- Modify: `src/market_briefing/storage.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write failing feedback tests**

Create `tests/test_feedback.py`:

```python
from datetime import datetime, timezone

from market_briefing.domain import FeedbackEntry
from market_briefing.feedback import summarize_feedback, validate_feedback_entry
from market_briefing.storage import BriefingStore


def test_validate_feedback_rejects_score_outside_one_to_five():
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=6,
        tags=["insufficient_risk"],
        note="风险提示可以更具体。",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    assert validate_feedback_entry(entry) == ["score must be between 1 and 5"]


def test_summarize_feedback_returns_compact_next_run_context():
    entries = [
        FeedbackEntry(
            feedback_id="feedback-001",
            report_id="report-001",
            section_id="risk_points",
            score=4,
            tags=["insufficient_risk", "unclear_citation"],
            note="风险提示要引用更清楚。",
            created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
        ),
        FeedbackEntry(
            feedback_id="feedback-002",
            report_id="report-001",
            section_id="market_indices",
            score=5,
            tags=[],
            note="指数部分清楚。",
            created_at=datetime(2026, 7, 2, 9, 5, tzinfo=timezone.utc),
        ),
    ]

    summary = summarize_feedback(entries)

    assert "Average score: 4.5" in summary
    assert "risk_points: score=4; tags=insufficient_risk,unclear_citation; note=风险提示要引用更清楚。" in summary
    assert "market_indices: score=5; tags=; note=指数部分清楚。" in summary


def test_store_round_trips_feedback(tmp_path):
    store = BriefingStore(tmp_path / "briefing.sqlite")
    store.initialize()
    entry = FeedbackEntry(
        feedback_id="feedback-001",
        report_id="report-001",
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk"],
        note="风险提示要引用更清楚。",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )

    store.save_feedback(entry)
    loaded = store.list_feedback("report-001")

    assert loaded == [entry]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_feedback.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.feedback'
```

- [ ] **Step 3: Implement feedback helpers**

Create `src/market_briefing/feedback.py`:

```python
from __future__ import annotations

from market_briefing.domain import FeedbackEntry


ALLOWED_FEEDBACK_TAGS = {
    "missing_key_point",
    "weak_source",
    "too_verbose",
    "too_much_opinion",
    "insufficient_risk",
    "unclear_citation",
}


def validate_feedback_entry(entry: FeedbackEntry) -> list[str]:
    errors: list[str] = []
    if entry.score < 1 or entry.score > 5:
        errors.append("score must be between 1 and 5")
    unknown_tags = [tag for tag in entry.tags if tag not in ALLOWED_FEEDBACK_TAGS]
    if unknown_tags:
        errors.append(f"unknown feedback tags: {','.join(unknown_tags)}")
    if len(entry.note) > 240:
        errors.append("note must be 240 characters or fewer")
    return errors


def summarize_feedback(entries: list[FeedbackEntry]) -> str:
    if not entries:
        return "No previous feedback."
    average = sum(entry.score for entry in entries) / len(entries)
    lines = [f"Average score: {average:.1f}"]
    lines.extend(entry.summary_line() for entry in entries)
    return "\n".join(lines)
```

- [ ] **Step 4: Extend storage with feedback table and methods**

Modify `SCHEMA` in `src/market_briefing/storage.py` by appending:

```python
create table if not exists feedback (
    feedback_id text primary key,
    report_id text not null,
    section_id text not null,
    score integer not null,
    tags text not null,
    note text not null,
    created_at text not null
);
```

Add imports:

```python
from market_briefing.domain import FeedbackEntry
```

Add methods to `BriefingStore`:

```python
    def save_feedback(self, entry: FeedbackEntry) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                insert into feedback (feedback_id, report_id, section_id, score, tags, note, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.feedback_id,
                    entry.report_id,
                    entry.section_id,
                    entry.score,
                    json.dumps(entry.tags, ensure_ascii=False),
                    entry.note,
                    entry.created_at.isoformat(),
                ),
            )

    def list_feedback(self, report_id: str) -> list[FeedbackEntry]:
        with self.connect() as connection:
            rows = connection.execute(
                "select * from feedback where report_id = ? order by created_at, feedback_id",
                (report_id,),
            ).fetchall()
        return [
            FeedbackEntry(
                feedback_id=row["feedback_id"],
                report_id=row["report_id"],
                section_id=row["section_id"],
                score=row["score"],
                tags=json.loads(row["tags"]),
                note=row["note"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
```

- [ ] **Step 5: Run feedback tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_feedback.py -v
```

Expected:

```text
tests/test_feedback.py::test_validate_feedback_rejects_score_outside_one_to_five PASSED
tests/test_feedback.py::test_summarize_feedback_returns_compact_next_run_context PASSED
tests/test_feedback.py::test_store_round_trips_feedback PASSED
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/market_briefing/feedback.py src/market_briefing/storage.py tests/test_feedback.py
git commit -m "feat: persist report feedback loop"
```

## Task 8: End-to-End Fixture Pipeline

**Files:**
- Create: `src/market_briefing/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Create `tests/test_pipeline.py`:

```python
from pathlib import Path

from market_briefing.config import AppConfig
from market_briefing.domain import ReportType
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore


def _config(tmp_path):
    return AppConfig(
        database_path=tmp_path / "briefing.sqlite",
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        generation_provider="template",
        report_modules={
            ReportType.AFTER_CLOSE: {
                "market_indices": True,
                "policy_regulation": True,
                "risk_points": True,
            },
            ReportType.PRE_OPEN_UPDATE: {
                "overnight_context": True,
                "today_watchpoints": True,
            },
        },
    )


def test_fixture_pipeline_generates_auditable_after_close_report(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    result = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-after-close-001",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )

    assert result.report.report_id == "report-run-after-close-001"
    assert Path(result.report.markdown_path).exists()
    assert Path(result.report.html_path).exists()
    assert Path(result.report.fact_ledger_path).exists()
    assert len(store.list_snapshots("run-after-close-001")) == 3
    assert len(store.list_facts("run-after-close-001")) == 4
    assert "A股盘后简报 2026-07-02" in Path(result.report.markdown_path).read_text(encoding="utf-8")


def test_fixture_pipeline_generates_pre_open_report(tmp_path):
    config = _config(tmp_path)
    store = BriefingStore(config.database_path)
    store.initialize()

    result = run_fixture_pipeline(
        PipelineRequest(
            run_id="run-pre-open-001",
            report_date="2026-07-03",
            report_type=ReportType.PRE_OPEN_UPDATE,
            fixture_path=Path("tests/fixtures/pre_open_sources.json"),
        ),
        config=config,
        store=store,
    )

    assert result.report.title == "A股早盘补充 2026-07-03"
    assert len(store.list_facts("run-pre-open-001")) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_pipeline.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.pipeline'
```

- [ ] **Step 3: Implement fixture pipeline**

Create `src/market_briefing/pipeline.py`:

```python
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from market_briefing.collectors.fixtures import FixtureCollector
from market_briefing.config import AppConfig, load_config
from market_briefing.domain import Report, ReportType, Run
from market_briefing.reporting import build_report, render_html, render_markdown
from market_briefing.storage import BriefingStore, build_report_paths
from market_briefing.validation import validate_report_sections


@dataclass(frozen=True)
class PipelineRequest:
    run_id: str
    report_date: str
    report_type: ReportType
    fixture_path: Path


@dataclass(frozen=True)
class PipelineResult:
    report: Report
    validation_errors: list[str]


def run_fixture_pipeline(request: PipelineRequest, config: AppConfig, store: BriefingStore) -> PipelineResult:
    enabled_modules = config.enabled_modules(request.report_type)
    run = Run.create(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
    )
    store.save_run(run)

    collection = FixtureCollector(request.fixture_path).collect(
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        enabled_modules=enabled_modules,
        raw_dir=config.raw_dir,
    )
    for snapshot in collection.snapshots:
        store.save_snapshot(snapshot)
    store.save_facts(collection.facts)

    paths = build_report_paths(config.reports_dir, request.report_date, request.report_type, request.run_id)
    paths.report_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(
        report_id=f"report-{request.run_id}",
        run_id=request.run_id,
        report_date=request.report_date,
        report_type=request.report_type,
        facts=collection.facts,
        markdown_path=str(paths.markdown_path),
        html_path=str(paths.html_path),
        fact_ledger_path=str(paths.fact_ledger_path),
    )
    validation = validate_report_sections(report.sections, collection.facts)
    markdown = render_markdown(report, collection.facts)
    html = render_html(markdown)
    paths.markdown_path.write_text(markdown, encoding="utf-8")
    paths.html_path.write_text(html, encoding="utf-8")
    paths.fact_ledger_path.write_text(
        json.dumps([fact.to_record() for fact in collection.facts], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store.save_report(report)
    return PipelineResult(report=report, validation_errors=validation.errors)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--report-type", choices=[item.value for item in ReportType], required=True)
    parser.add_argument("--fixture-path", required=True)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    store = BriefingStore(config.database_path)
    store.initialize()
    result = run_fixture_pipeline(
        PipelineRequest(
            run_id=args.run_id,
            report_date=args.report_date,
            report_type=ReportType(args.report_type),
            fixture_path=Path(args.fixture_path),
        ),
        config=config,
        store=store,
    )
    print(result.report.markdown_path)
```

- [ ] **Step 4: Run pipeline tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_pipeline.py -v
```

Expected:

```text
tests/test_pipeline.py::test_fixture_pipeline_generates_auditable_after_close_report PASSED
tests/test_pipeline.py::test_fixture_pipeline_generates_pre_open_report PASSED
```

- [ ] **Step 5: Run CLI smoke command**

Run:

```powershell
.\.venv\Scripts\market-briefing --run-id manual-after-close-001 --report-date 2026-07-02 --report-type after_close --fixture-path tests/fixtures/after_close_sources.json
```

Expected:

```text
reports\2026-07-02\after_close\manual-after-close-001\briefing.md
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/market_briefing/pipeline.py tests/test_pipeline.py
git commit -m "feat: run auditable fixture pipeline"
```

## Task 9: Optional LLM Boundary With Validation Fallback

**Files:**
- Create: `src/market_briefing/llm.py`
- Modify: `src/market_briefing/reporting.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing LLM boundary tests**

Create `tests/test_llm.py`:

```python
from datetime import datetime, timezone

from market_briefing.domain import AtomicFact, FactClassification, ReportSection, ReportType, SourceType
from market_briefing.llm import LLMProvider, generate_with_optional_llm


class BadProvider(LLMProvider):
    def generate_sections(self, facts, feedback_summary):
        return [
            ReportSection(
                section_id="risk_points",
                title="风险提示",
                body="建议买入某公司股票。[fact-missing]",
                fact_ids=["fact-missing"],
                status="ok",
            )
        ]


class GoodProvider(LLMProvider):
    def generate_sections(self, facts, feedback_summary):
        return [
            ReportSection(
                section_id="market_indices",
                title="指数表现",
                body="上证指数收涨。[fact-001]",
                fact_ids=["fact-001"],
                status="ok",
            )
        ]


def _fact():
    now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    return AtomicFact(
        fact_id="fact-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        module="market_indices",
        claim="上证指数收涨。",
        classification=FactClassification.FACT,
        source_name="Fixture",
        source_url="fixture://source",
        source_type=SourceType.DATA_API,
        published_at=now,
        fetched_at=now,
        confidence="high",
        raw_snapshot_path="data/raw/source.json",
        used_in_sections=["market_indices"],
    )


def test_bad_llm_output_falls_back_to_template_report():
    result = generate_with_optional_llm(
        provider=BadProvider(),
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=[_fact()],
        feedback_summary="No previous feedback.",
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert result.used_fallback is True
    assert result.validation_errors == [
        "section risk_points cites missing fact_id fact-missing",
        "section risk_points contains banned phrase 建议买入",
    ]
    assert result.report.sections[0].section_id == "market_indices"


def test_good_llm_output_is_used():
    result = generate_with_optional_llm(
        provider=GoodProvider(),
        report_id="report-001",
        run_id="run-001",
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        facts=[_fact()],
        feedback_summary="No previous feedback.",
        markdown_path="reports/briefing.md",
        html_path="reports/briefing.html",
        fact_ledger_path="reports/fact_ledger.json",
    )

    assert result.used_fallback is False
    assert result.report.sections[0].body == "上证指数收涨。[fact-001]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.llm'
```

- [ ] **Step 3: Implement LLM provider boundary**

Create `src/market_briefing/llm.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from market_briefing.domain import AtomicFact, Report, ReportSection, ReportType
from market_briefing.reporting import build_report
from market_briefing.validation import validate_report_sections


class LLMProvider(Protocol):
    def generate_sections(self, facts: list[AtomicFact], feedback_summary: str) -> list[ReportSection]:
        ...


@dataclass(frozen=True)
class GeneratedReportResult:
    report: Report
    used_fallback: bool
    validation_errors: list[str]


def generate_with_optional_llm(
    provider: LLMProvider | None,
    report_id: str,
    run_id: str,
    report_date: str,
    report_type: ReportType,
    facts: list[AtomicFact],
    feedback_summary: str,
    markdown_path: str,
    html_path: str,
    fact_ledger_path: str,
) -> GeneratedReportResult:
    fallback = build_report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        facts=facts,
        markdown_path=markdown_path,
        html_path=html_path,
        fact_ledger_path=fact_ledger_path,
    )
    if provider is None:
        return GeneratedReportResult(report=fallback, used_fallback=True, validation_errors=[])

    sections = provider.generate_sections(facts, feedback_summary)
    validation = validate_report_sections(sections, facts)
    if not validation.ok:
        return GeneratedReportResult(report=fallback, used_fallback=True, validation_errors=validation.errors)

    llm_report = Report(
        report_id=report_id,
        run_id=run_id,
        report_date=report_date,
        report_type=report_type,
        title=fallback.title,
        sections=sections,
        markdown_path=markdown_path,
        html_path=html_path,
        fact_ledger_path=fact_ledger_path,
    )
    return GeneratedReportResult(report=llm_report, used_fallback=False, validation_errors=[])
```

- [ ] **Step 4: Run LLM tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_llm.py -v
```

Expected:

```text
tests/test_llm.py::test_bad_llm_output_falls_back_to_template_report PASSED
tests/test_llm.py::test_good_llm_output_is_used PASSED
```

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/market_briefing/llm.py tests/test_llm.py
git commit -m "feat: guard optional llm briefing output"
```

## Task 10: Loop First Dashboard

**Files:**
- Create: `src/market_briefing/app.py`
- Create: `src/market_briefing/templates/base.html`
- Create: `src/market_briefing/templates/dashboard.html`
- Create: `src/market_briefing/templates/report.html`
- Create: `src/market_briefing/templates/run.html`
- Create: `src/market_briefing/static/styles.css`
- Modify: `src/market_briefing/storage.py`
- Create: `tests/test_web.py`

- [ ] **Step 1: Write failing web tests**

Create `tests/test_web.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from market_briefing.app import create_app
from market_briefing.config import AppConfig
from market_briefing.domain import ReportType
from market_briefing.storage import BriefingStore


def _client(tmp_path):
    config = AppConfig(
        database_path=tmp_path / "briefing.sqlite",
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        generation_provider="template",
        report_modules={
            ReportType.AFTER_CLOSE: {"market_indices": True, "policy_regulation": True, "risk_points": True},
            ReportType.PRE_OPEN_UPDATE: {"overnight_context": True, "today_watchpoints": True},
        },
    )
    store = BriefingStore(config.database_path)
    store.initialize()
    return TestClient(create_app(config=config, store=store)), store


def test_dashboard_renders_loop_first_sections(tmp_path):
    client, _store = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert "Loop Dashboard" in response.text
    assert "Fact ledger" in response.text
    assert "Section feedback" in response.text


def test_dashboard_can_trigger_fixture_run_and_show_report(tmp_path):
    client, _store = _client(tmp_path)

    response = client.post(
        "/runs/fixture",
        data={
            "run_id": "web-run-001",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    report_response = client.get(response.headers["location"])
    assert report_response.status_code == 200
    assert "A股盘后简报 2026-07-02" in report_response.text
    assert "fact-market-001" in report_response.text


def test_dashboard_can_submit_feedback(tmp_path):
    client, _store = _client(tmp_path)
    client.post(
        "/runs/fixture",
        data={
            "run_id": "web-run-002",
            "report_date": "2026-07-02",
            "report_type": "after_close",
            "fixture_path": "tests/fixtures/after_close_sources.json",
        },
        follow_redirects=False,
    )

    response = client.post(
        "/reports/report-web-run-002/feedback",
        data={
            "section_id": "risk_points",
            "score": "4",
            "tags": ["insufficient_risk", "unclear_citation"],
            "note": "风险提示需要更清楚引用事实。",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    page = client.get("/reports/report-web-run-002")
    assert "风险提示需要更清楚引用事实。" in page.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_web.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.app'
```

- [ ] **Step 3: Extend storage for dashboard queries**

Add these methods to `BriefingStore` in `src/market_briefing/storage.py`:

```python
    def list_reports(self) -> list[Report]:
        with self.connect() as connection:
            rows = connection.execute("select report_id from reports order by report_date desc, report_id desc").fetchall()
        return [self.get_report(row["report_id"]) for row in rows]

    def latest_report(self) -> Report | None:
        reports = self.list_reports()
        return reports[0] if reports else None
```

- [ ] **Step 4: Implement FastAPI app**

Create `src/market_briefing/app.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from market_briefing.config import AppConfig, load_config
from market_briefing.domain import FeedbackEntry, ReportType
from market_briefing.feedback import summarize_feedback, validate_feedback_entry
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore


PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def create_app(config: AppConfig | None = None, store: BriefingStore | None = None) -> FastAPI:
    app_config = config or load_config(Path("configs/default.yaml"))
    app_store = store or BriefingStore(app_config.database_path)
    app_store.initialize()

    app = FastAPI(title="Market Daily Briefing")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        report = app_store.latest_report()
        feedback = app_store.list_feedback(report.report_id) if report else []
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "report": report,
                "reports": app_store.list_reports(),
                "feedback_summary": summarize_feedback(feedback),
            },
        )

    @app.post("/runs/fixture")
    def create_fixture_run(
        run_id: str = Form(...),
        report_date: str = Form(...),
        report_type: str = Form(...),
        fixture_path: str = Form(...),
    ):
        result = run_fixture_pipeline(
            PipelineRequest(
                run_id=run_id,
                report_date=report_date,
                report_type=ReportType(report_type),
                fixture_path=Path(fixture_path),
            ),
            config=app_config,
            store=app_store,
        )
        return RedirectResponse(url=f"/reports/{result.report.report_id}", status_code=303)

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    def show_report(request: Request, report_id: str):
        report = app_store.get_report(report_id)
        facts = app_store.list_facts(report.run_id)
        snapshots = app_store.list_snapshots(report.run_id)
        feedback = app_store.list_feedback(report_id)
        return templates.TemplateResponse(
            "report.html",
            {
                "request": request,
                "report": report,
                "facts": facts,
                "snapshots": snapshots,
                "feedback": feedback,
                "feedback_summary": summarize_feedback(feedback),
            },
        )

    @app.post("/reports/{report_id}/feedback")
    def submit_feedback(
        report_id: str,
        section_id: str = Form(...),
        score: int = Form(...),
        tags: list[str] = Form(default=[]),
        note: str = Form(default=""),
    ):
        entry = FeedbackEntry(
            feedback_id=f"feedback-{uuid4().hex}",
            report_id=report_id,
            section_id=section_id,
            score=score,
            tags=tags,
            note=note,
            created_at=datetime.now(timezone.utc),
        )
        errors = validate_feedback_entry(entry)
        if errors:
            raise ValueError("; ".join(errors))
        app_store.save_feedback(entry)
        return RedirectResponse(url=f"/reports/{report_id}", status_code=303)

    return app


app = create_app()
```

- [ ] **Step 5: Implement templates and CSS**

Create `src/market_briefing/templates/base.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title or "Market Daily Briefing" }}</title>
    <link rel="stylesheet" href="/static/styles.css">
  </head>
  <body>
    <main class="shell">
      {% block content %}{% endblock %}
    </main>
  </body>
</html>
```

Create `src/market_briefing/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block content %}
<header class="toolbar">
  <div>
    <h1>Loop Dashboard</h1>
    <p>Auditable A-share daily briefing workspace</p>
  </div>
</header>
<section class="grid">
  <article class="panel">
    <h2>Run fixture briefing</h2>
    <form method="post" action="/runs/fixture" class="form-grid">
      <input name="run_id" value="manual-run-001">
      <input name="report_date" value="2026-07-02">
      <select name="report_type">
        <option value="after_close">after_close</option>
        <option value="pre_open_update">pre_open_update</option>
      </select>
      <input name="fixture_path" value="tests/fixtures/after_close_sources.json">
      <button type="submit">Run</button>
    </form>
  </article>
  <article class="panel">
    <h2>Section feedback</h2>
    <pre>{{ feedback_summary }}</pre>
  </article>
  <article class="panel span-2">
    <h2>Fact ledger</h2>
    {% if report %}
      <p>Latest report: <a href="/reports/{{ report.report_id }}">{{ report.title }}</a></p>
    {% else %}
      <p>No report generated yet.</p>
    {% endif %}
  </article>
</section>
{% endblock %}
```

Create `src/market_briefing/templates/report.html`:

```html
{% extends "base.html" %}
{% block content %}
<a href="/">Back</a>
<h1>{{ report.title }}</h1>
<section class="grid">
  <article class="panel">
    {% for section in report.sections %}
      <section class="section">
        <h2>{{ section.title }}</h2>
        <pre>{{ section.body }}</pre>
      </section>
    {% endfor %}
  </article>
  <aside class="panel">
    <h2>Fact ledger</h2>
    {% for fact in facts %}
      <div class="fact">
        <strong>{{ fact.fact_id }}</strong>
        <p>{{ fact.claim }}</p>
        <a href="{{ fact.source_url }}">{{ fact.source_name }}</a>
      </div>
    {% endfor %}
    <h2>Raw snapshots</h2>
    {% for snapshot in snapshots %}
      <p>{{ snapshot.module }}: {{ snapshot.raw_path }}</p>
    {% endfor %}
    <h2>Section feedback</h2>
    <form method="post" action="/reports/{{ report.report_id }}/feedback" class="form-grid">
      <input name="section_id" value="risk_points">
      <input name="score" type="number" min="1" max="5" value="4">
      <label><input type="checkbox" name="tags" value="insufficient_risk"> insufficient_risk</label>
      <label><input type="checkbox" name="tags" value="unclear_citation"> unclear_citation</label>
      <input name="note" value="">
      <button type="submit">Save feedback</button>
    </form>
    {% for item in feedback %}
      <p>{{ item.summary_line() }}</p>
    {% endfor %}
  </aside>
</section>
{% endblock %}
```

Create `src/market_briefing/templates/run.html`:

```html
{% extends "base.html" %}
{% block content %}
<h1>Run</h1>
<p>{{ message }}</p>
{% endblock %}
```

Create `src/market_briefing/static/styles.css`:

```css
body {
  margin: 0;
  font-family: Arial, sans-serif;
  background: #f5f7f9;
  color: #17202a;
}

.shell {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: 16px;
}

.panel {
  background: #ffffff;
  border: 1px solid #d8dee6;
  border-radius: 8px;
  padding: 16px;
}

.span-2 {
  grid-column: span 2;
}

.form-grid {
  display: grid;
  gap: 8px;
}

input, select, button {
  padding: 8px;
  border: 1px solid #b8c1cc;
  border-radius: 6px;
}

button {
  background: #1f6feb;
  color: white;
  cursor: pointer;
}

pre {
  white-space: pre-wrap;
}

.fact {
  border-top: 1px solid #e5e9ef;
  padding: 8px 0;
}
```

- [ ] **Step 6: Run web tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_web.py -v
```

Expected:

```text
tests/test_web.py::test_dashboard_renders_loop_first_sections PASSED
tests/test_web.py::test_dashboard_can_trigger_fixture_run_and_show_report PASSED
tests/test_web.py::test_dashboard_can_submit_feedback PASSED
```

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/market_briefing/app.py src/market_briefing/templates src/market_briefing/static src/market_briefing/storage.py tests/test_web.py
git commit -m "feat: add loop first dashboard"
```

## Task 11: Real Source Adapter Contracts

**Files:**
- Create: `src/market_briefing/collectors/market_data.py`
- Create: `src/market_briefing/collectors/official_sources.py`
- Create: `tests/test_real_source_adapters.py`

- [ ] **Step 1: Write failing adapter tests with mocked clients**

Create `tests/test_real_source_adapters.py`:

```python
from pathlib import Path

import httpx

from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.collectors.official_sources import OfficialSourceCollector, OfficialSourceTarget
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_real_source_adapters.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'market_briefing.collectors.market_data'
```

- [ ] **Step 3: Implement market data collector with an injectable client**

Create `src/market_briefing/collectors/market_data.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import AtomicFact, FactClassification, RawSnapshot, ReportType, SourceType


class MarketDataClient(Protocol):
    def index_spot(self) -> list[dict]:
        ...

    def sector_spot(self) -> list[dict]:
        ...


class MarketDataCollector:
    def __init__(self, client: MarketDataClient):
        self.client = client

    def collect(
        self,
        run_id: str,
        report_date: str,
        report_type: ReportType,
        enabled_modules: list[str],
        raw_dir: Path,
    ) -> CollectionResult:
        fetched_at = datetime.now(timezone.utc)
        snapshots: list[RawSnapshot] = []
        facts: list[AtomicFact] = []

        if "market_indices" in enabled_modules:
            rows = self.client.index_spot()
            raw_path = _write_json(raw_dir, report_date, run_id, "market_indices", rows)
            snapshots.append(_snapshot(run_id, "market_indices", "AkShare adapter", "akshare://index_spot", raw_path, fetched_at, len(rows)))
            for index, row in enumerate(rows, start=1):
                facts.append(
                    AtomicFact(
                        fact_id=f"fact-market-index-{index:03d}",
                        run_id=run_id,
                        report_date=report_date,
                        report_type=report_type,
                        module="market_indices",
                        claim=f"{row['name']}收于 {row['close']} 点，涨幅 {row['change_pct']}%。",
                        classification=FactClassification.FACT,
                        source_name="AkShare adapter",
                        source_url="akshare://index_spot",
                        source_type=SourceType.DATA_API,
                        published_at=None,
                        fetched_at=fetched_at,
                        confidence="medium",
                        raw_snapshot_path=str(raw_path),
                        used_in_sections=["market_indices"],
                    )
                )

        if "sector_moves" in enabled_modules:
            rows = self.client.sector_spot()
            raw_path = _write_json(raw_dir, report_date, run_id, "sector_moves", rows)
            snapshots.append(_snapshot(run_id, "sector_moves", "AkShare adapter", "akshare://sector_spot", raw_path, fetched_at, len(rows)))
            for index, row in enumerate(rows, start=1):
                facts.append(
                    AtomicFact(
                        fact_id=f"fact-sector-{index:03d}",
                        run_id=run_id,
                        report_date=report_date,
                        report_type=report_type,
                        module="sector_moves",
                        claim=f"{row['name']}板块涨跌幅为 {row['change_pct']}%。",
                        classification=FactClassification.FACT,
                        source_name="AkShare adapter",
                        source_url="akshare://sector_spot",
                        source_type=SourceType.DATA_API,
                        published_at=None,
                        fetched_at=fetched_at,
                        confidence="medium",
                        raw_snapshot_path=str(raw_path),
                        used_in_sections=["sector_moves"],
                    )
                )

        return CollectionResult(snapshots=snapshots, facts=facts)


def _write_json(raw_dir: Path, report_date: str, run_id: str, module: str, rows: list[dict]) -> Path:
    path = raw_dir / report_date / run_id / f"{module}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _snapshot(run_id: str, module: str, source_name: str, source_url: str, raw_path: Path, fetched_at: datetime, rows: int) -> RawSnapshot:
    return RawSnapshot(
        snapshot_id=f"{run_id}-{module}",
        run_id=run_id,
        module=module,
        source_name=source_name,
        source_url=source_url,
        source_type=SourceType.DATA_API,
        fetched_at=fetched_at,
        content_type="application/json",
        raw_path=str(raw_path),
        metadata={"rows": rows},
    )
```

- [ ] **Step 4: Implement official source collector**

Create `src/market_briefing/collectors/official_sources.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from market_briefing.collectors.base import CollectionResult
from market_briefing.domain import AtomicFact, FactClassification, RawSnapshot, ReportType, SourceType


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
        snapshots: list[RawSnapshot] = []
        facts: list[AtomicFact] = []

        for index, target in enumerate(self.targets, start=1):
            if target.module not in enabled_modules:
                continue
            response = self.client.get(target.source_url, timeout=15)
            response.raise_for_status()
            raw_path = raw_dir / report_date / run_id / f"{target.module}-{index:03d}.html"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(response.text, encoding="utf-8")
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
        OfficialSourceTarget("policy_regulation", "中国证监会", "https://www.csrc.gov.cn/", SourceType.OFFICIAL),
        OfficialSourceTarget("policy_regulation", "上海证券交易所", "https://www.sse.com.cn/", SourceType.EXCHANGE),
        OfficialSourceTarget("policy_regulation", "深圳证券交易所", "https://www.szse.cn/", SourceType.EXCHANGE),
    ]


def _extract_title_and_first_paragraph(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("h1") or soup.find("title"))
    paragraph = soup.find("p")
    title_text = title.get_text(strip=True) if title else "官方信息"
    paragraph_text = paragraph.get_text(strip=True) if paragraph else "页面已抓取，需人工复核正文。"
    return title_text, paragraph_text
```

- [ ] **Step 5: Run adapter tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_real_source_adapters.py -v
```

Expected:

```text
tests/test_real_source_adapters.py::test_market_data_collector_normalizes_indices_and_sectors PASSED
tests/test_real_source_adapters.py::test_official_source_collector_extracts_official_fact PASSED
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/market_briefing/collectors/market_data.py src/market_briefing/collectors/official_sources.py tests/test_real_source_adapters.py
git commit -m "feat: add real source adapter contracts"
```

## Task 12: Acceptance Smoke Tests and README

**Files:**
- Create: `tests/test_acceptance.py`
- Modify: `README.md`

- [ ] **Step 1: Write acceptance test**

Create `tests/test_acceptance.py`:

```python
from pathlib import Path

from market_briefing.config import AppConfig
from market_briefing.domain import FeedbackEntry, ReportType
from market_briefing.feedback import summarize_feedback
from market_briefing.pipeline import PipelineRequest, run_fixture_pipeline
from market_briefing.storage import BriefingStore
from datetime import datetime, timezone


def test_mvp_acceptance_two_rhythms_audit_and_feedback(tmp_path):
    config = AppConfig(
        database_path=tmp_path / "briefing.sqlite",
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        generation_provider="template",
        report_modules={
            ReportType.AFTER_CLOSE: {"market_indices": True, "policy_regulation": True, "risk_points": True},
            ReportType.PRE_OPEN_UPDATE: {"overnight_context": True, "today_watchpoints": True},
        },
    )
    store = BriefingStore(config.database_path)
    store.initialize()

    after_close = run_fixture_pipeline(
        PipelineRequest(
            run_id="accept-after-close",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            fixture_path=Path("tests/fixtures/after_close_sources.json"),
        ),
        config=config,
        store=store,
    )
    pre_open = run_fixture_pipeline(
        PipelineRequest(
            run_id="accept-pre-open",
            report_date="2026-07-03",
            report_type=ReportType.PRE_OPEN_UPDATE,
            fixture_path=Path("tests/fixtures/pre_open_sources.json"),
        ),
        config=config,
        store=store,
    )
    feedback = FeedbackEntry(
        feedback_id="feedback-accept-001",
        report_id=after_close.report.report_id,
        section_id="risk_points",
        score=4,
        tags=["insufficient_risk"],
        note="下一次风险提示要更具体。",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )
    store.save_feedback(feedback)

    assert Path(after_close.report.markdown_path).exists()
    assert Path(after_close.report.html_path).exists()
    assert Path(after_close.report.fact_ledger_path).exists()
    assert Path(pre_open.report.markdown_path).exists()
    assert len(store.list_snapshots("accept-after-close")) == 3
    assert len(store.list_facts("accept-after-close")) == 4
    assert "下一次风险提示要更具体。" in summarize_feedback(store.list_feedback(after_close.report.report_id))
```

- [ ] **Step 2: Run acceptance test**

Run:

```powershell
.\.venv\Scripts\python -m pytest tests/test_acceptance.py -v
```

Expected:

```text
tests/test_acceptance.py::test_mvp_acceptance_two_rhythms_audit_and_feedback PASSED
```

- [ ] **Step 3: Update README with local commands**

Replace `README.md` with:

```markdown
# Market Daily Briefing

Local MVP for learning loop engineering through an auditable A-share daily market briefing.

## What it does

- Generates `after_close` and `pre_open_update` reports.
- Saves raw snapshots, atomic facts, Markdown, HTML, and a fact ledger.
- Shows a Loop First dashboard for report review, fact inspection, and section feedback.
- Uses template generation by default and keeps an optional LLM boundary behind validation.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Install optional market data dependencies:

```powershell
.\.venv\Scripts\python -m pip install -e ".[sources]"
```

## Run tests

```powershell
.\.venv\Scripts\python -m pytest -v
```

## Generate fixture reports

```powershell
.\.venv\Scripts\market-briefing --run-id manual-after-close-001 --report-date 2026-07-02 --report-type after_close --fixture-path tests/fixtures/after_close_sources.json
.\.venv\Scripts\market-briefing --run-id manual-pre-open-001 --report-date 2026-07-03 --report-type pre_open_update --fixture-path tests/fixtures/pre_open_sources.json
```

## Start dashboard

```powershell
.\.venv\Scripts\python -m uvicorn market_briefing.app:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000.

## Safety boundary

This project is for market briefing and loop-engineering practice. It does not provide buy/sell advice, target prices, position sizing, or stock recommendations.
```

- [ ] **Step 4: Run full test suite**

Run:

```powershell
.\.venv\Scripts\python -m pytest -v
```

Expected:

```text
PASSED
```

The exact number of passed tests depends on whether all tasks above have been implemented, but there should be no failures.

- [ ] **Step 5: Run formatter/linter**

Run:

```powershell
.\.venv\Scripts\python -m ruff check src tests
```

Expected:

```text
All checks passed!
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add README.md tests/test_acceptance.py
git commit -m "test: add mvp acceptance coverage"
```

## Implementation Order and Review Gates

Execute tasks in order. After each task:

1. Run the task-specific tests.
2. Run `.\.venv\Scripts\python -m pytest -q` if the task changed shared code.
3. Commit with the task's commit command.
4. Review the diff before starting the next task.

Review gates:

- After Task 4, verify the schema matches the fact-ledger fields in the design spec.
- After Task 8, manually open the generated Markdown and HTML files.
- After Task 10, run the dashboard and confirm feedback persists after page reload.
- After Task 12, confirm both report rhythms produce traceable raw snapshots, facts, reports, and feedback summaries.
