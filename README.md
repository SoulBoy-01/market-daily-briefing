# Market Daily Briefing

Local MVP for learning loop engineering through an auditable A-share daily market
briefing.

## What It Does

- Generates `after_close` and `pre_open_update` market briefing reports.
- Stores raw source snapshots, atomic facts, Markdown, HTML, and a JSON fact ledger.
- Provides a Loop First dashboard for reviewing reports, facts, sources, and feedback.
- Uses deterministic template generation by default, with an optional LLM boundary kept behind validation.

## Setup

```powershell
py -3.11 -m venv .venv
# If the Windows launcher cannot find 3.11, use: python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Optional source adapter dependencies:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,sources]"
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest -v
```

## Generate Fixture Reports

```powershell
.\.venv\Scripts\python -m market_briefing.pipeline --run-id fixture-after-close-20260702 --report-date 2026-07-02 --report-type after_close --fixture-path tests\fixtures\after_close_sources.json
.\.venv\Scripts\python -m market_briefing.pipeline --run-id fixture-pre-open-20260703 --report-date 2026-07-03 --report-type pre_open_update --fixture-path tests\fixtures\pre_open_sources.json
```

## Start Dashboard

```powershell
.\.venv\Scripts\python -m uvicorn market_briefing.app:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 in a browser, or use a second terminal/browser while uvicorn is running.

## Safety Boundary

This project does not provide buy/sell advice, target prices, position sizing, or
stock recommendations.
