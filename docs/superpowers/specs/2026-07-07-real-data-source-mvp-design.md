# Real Data Source MVP Design

Date: 2026-07-07
Status: Ready for user review

## Purpose

Extend the A-share daily briefing MVP from fixture-only operation to a real-data, auditable run path while preserving fixture and mock replay for learning, testing, and debugging.

The goal is not to maximize source coverage. The goal is to connect a small, reliable set of live sources into the existing loop:

```text
real source -> raw snapshot -> atomic facts -> report -> review UI -> feedback -> next run
```

The feature must preserve the core safety boundary: source verification, fact/opinion/inference separation, and no buy/sell or position advice.

## Chosen Scope

The first real-source version uses a mixed route:

- Market indices and sector moves come from a third-party data API adapter, initially through the existing AkShare-shaped adapter boundary.
- Policy and regulatory information comes from official or exchange web sources.
- Market news and institutional opinions are not automatically collected in this version, to avoid early fact/opinion contamination.
- Fixture and mock replay remain first-class paths.

This gives the report enough market shape to feel like a daily briefing while keeping the highest-risk interpretation layer small.

## Existing Codebase Context

The project already contains the main pieces needed for this feature:

- `MarketDataCollector` in `src/market_briefing/collectors/market_data.py`
  - Uses a `MarketDataClient` protocol with `index_spot()` and `sector_spot()`.
  - Produces `market_indices` and `sector_moves` facts.
  - Has tests using `FakeMarketClient`.
- `OfficialSourceCollector` in `src/market_briefing/collectors/official_sources.py`
  - Fetches official/exchange pages with `httpx`.
  - Stores HTML snapshots.
  - Currently extracts title and first paragraph from a single page.
  - Has tests using `httpx.MockTransport`.
- `run_fixture_pipeline` in `src/market_briefing/pipeline.py`
  - Owns run lifecycle, validation, persistence, report rendering, and previous-feedback context.

The real-source MVP should reuse these patterns instead of creating a second reporting system.

## Running Modes

The system will support three source modes:

1. `fixture`
   - Current deterministic fixture path.
   - Used for tests, tutorials, and reproducible debugging.

2. `mock_real`
   - Uses real-source pipeline logic with fake market and official clients.
   - Used for TDD and integration tests without network access.

3. `real`
   - Uses actual market and official source clients.
   - Requires optional dependencies and network access.
   - Must label third-party data clearly as `DATA_API`.

The CLI and web UI will call the same real-source pipeline function. CLI comes first for testability, but the first implementation slice should also expose a web button/form once the shared logic is covered.

## User-Facing Entry Points

CLI:

```powershell
market-briefing --source real --run-id real-after-close-20260707 --report-date 2026-07-07 --report-type after_close
```

Fixture CLI remains supported:

```powershell
market-briefing --source fixture --run-id fixture-after-close-20260707 --report-date 2026-07-07 --report-type after_close --fixture-path tests\fixtures\after_close_sources.json
```

Web UI:

- The dashboard keeps the existing fixture run form.
- A separate real-data run form/button is added.
- The UI must clearly distinguish fixture/sample data from real data.
- Real-data failures show warning summaries rather than stack traces.

## Source Policy

Market data:

- Source type: `DATA_API`.
- Expected modules: `market_indices`, `sector_moves`.
- Confidence: usually `medium`, because the source is a third-party adapter.
- Claims should be strictly numerical and descriptive, such as index close/change or sector move.
- No explanation or recommendation should be inferred from market data alone.

Official/regulatory data:

- Source type: `OFFICIAL` or `EXCHANGE`.
- Expected module: `policy_regulation`.
- Confidence: `high` for source publication facts when the source is official or exchange-owned.
- Claims should state that an official/exchange source published a named item.
- Details may summarize the first paragraph, but should remain descriptive.

News/opinion:

- Not collected automatically in this version.
- Existing fixture examples may still include `major_news` for learning.
- Future work can add media collection with strict `OPINION` or `UNVERIFIED` handling.

## Official Source Depth

The official/regulatory collector should support list plus detail capture.

List capture:

- Fetch an announcement/list page.
- Extract latest item title, link, and publication time when available.
- Save the list page as a raw snapshot.
- Generate a `FACT` that the source published the listed item.

Detail capture:

- Fetch the detail page for each selected list item.
- Save the detail page as a second raw snapshot or linked raw file.
- Extract the first paragraph or short summary if available.
- Add the detail text to the claim only when it is directly extracted from the official/exchange detail page.

If list capture succeeds but detail capture fails:

- Keep the list-derived fact.
- Emit a warning for the failed detail fetch.
- Do not invent summary text.

If list capture fails:

- Treat that source as failed for critical-source evaluation.

## Failure Policy

The real-source pipeline uses partial success with explicit warnings.

Critical groups:

1. Market group
   - `market_indices` or `sector_moves` must produce at least one fact.

2. Official/regulatory group
   - `policy_regulation` must produce at least one `OFFICIAL` or `EXCHANGE` fact.

If either critical group fully fails:

- Mark the run as `FAILED`.
- Do not publish a normal report, fact ledger, or snapshots into the review ledger.
- Record source warning/error summaries for diagnosis.
- Successful fetches from that failed run are not persisted into the normal review ledger. A future quarantine/debug store is out of scope for this MVP.

If critical groups pass but some enabled source fails:

- Generate the report from available facts.
- Mark the run as `COMPLETED_WITH_WARNINGS`.
- Persist warning count and user-facing warning summaries.

If validation fails after collection:

- Preserve the existing rule: do not publish polluted reports, facts, or snapshots into the normal review ledger.
- Mark the run as `FAILED`.

No automatic fallback from real data to fixture data is allowed. Fixture mode must be explicit.

## Warning Model

The first version shows concise warnings:

```text
<source name> / <module> / <error summary>
```

Examples:

```text
Shanghai Stock Exchange / policy_regulation / HTTP 500
AkShare adapter / market_indices / missing column: close
```

Warning display:

- CLI prints warning summaries after the run.
- Dashboard and report pages show warning summaries near run/report metadata.
- The user-facing UI does not show Python stack traces.

Detailed error storage is deferred. A future version can add a structured warning table or JSON log with exception class, traceback, retry count, and request metadata.

## Data Model Impact

The current `Run` model has `warning_count` and `error_message`, but does not have structured warning records.

First implementation should avoid a large storage migration if possible:

- Use `warning_count` for run status summary.
- Store concise warning text in `error_message` when the run fails.
- For completed-with-warnings, add the smallest persistence needed to show warning summaries in CLI and web UI. If a migration is required, keep it narrow and covered by tests.

If structured warnings become too awkward to persist without schema churn, the implementation should introduce a `run_warnings` table with:

- `warning_id`
- `run_id`
- `source_name`
- `module`
- `message`
- `detail` optional
- `created_at`

This table is preferable to overloading report sections with operational errors.

## Pipeline Shape

Add a real-source pipeline function parallel to the fixture path:

```text
run_real_pipeline(request, config, store, collector_bundle)
```

The function should share the report-building and validation path with fixture runs:

1. Create run.
2. Collect from market and official collectors.
3. Aggregate facts, snapshots, and warnings.
4. Apply critical-group checks.
5. Build report from available facts.
6. Validate report sections.
7. Persist snapshots/facts/report only if publication is allowed.
8. Save final run status as `COMPLETED`, `COMPLETED_WITH_WARNINGS`, or `FAILED`.

Avoid duplicating report rendering logic between fixture and real runs. Shared helpers can be extracted from `run_fixture_pipeline` only when they reduce duplication without obscuring audit behavior.

## Validation Rules

Existing validation rules remain in force:

- `one_sentence_conclusion` only cites `FACT`.
- `next_watchlist` and `today_watchpoints` reject `OPINION` and `UNVERIFIED`.
- `market_overview` and `sector_strength` reject `UNVERIFIED` and require rooted inferences.
- Banned investment-advice phrases remain prohibited.

Additional real-source rules:

- Third-party market facts are never `OFFICIAL`.
- Official/regulatory critical-group success requires `source_type` of `OFFICIAL` or `EXCHANGE`.
- A failed source cannot generate facts.
- A detail-page failure cannot convert a list-page fact into an inference.

## Testing Strategy

Tests should not depend on live network access.

Required tests:

- Market collector still normalizes index and sector rows using fake clients.
- Official collector parses list plus detail pages using `httpx.MockTransport`.
- Detail failure preserves list fact and emits a warning.
- List failure marks that source failed.
- Real pipeline publishes a report when both critical groups have facts.
- Real pipeline marks `COMPLETED_WITH_WARNINGS` when critical groups pass but a non-blocking source/detail fails.
- Real pipeline marks `FAILED` and publishes no normal report when market group fails.
- Real pipeline marks `FAILED` and publishes no normal report when official/regulatory group fails.
- CLI can run fixture mode and real/mock mode through the same command surface.
- Web form triggers the same real pipeline path and renders warning summaries.

Live-source smoke tests can be manual or opt-in only, never part of the default test suite.

## Web UI Impact

Dashboard:

- Keep existing sample/fixture run form.
- Add a separate real-data run form.
- Label the real-data run form clearly as live/third-party/official-source based.
- Show warning summaries in the latest report/run area.

Report page:

- Show run status and warning summaries near report metadata.
- Keep raw snapshot and fact ledger inspection unchanged.
- Do not display operational warnings as market facts.

Empty or failed real runs:

- If the real run fails before publication, redirect or render an error state that explains which critical group failed.
- Do not show a report that looks complete when critical groups failed.

## Out of Scope

- Automatic scheduling.
- Alerts or push notifications.
- Full media/news ingestion.
- Full-text official announcement understanding.
- LLM summarization of official documents.
- Retries, backoff, and source health dashboards.
- Multi-user permission handling.
- Production deployment.

## Acceptance Criteria

- A user can run fixture mode exactly as before.
- A user can run real/mock mode from CLI.
- A user can trigger real data from the dashboard.
- Published real runs produce raw snapshots for every successful source fetch.
- Reports cite only persisted atomic facts.
- Third-party market facts are labeled as `DATA_API`.
- Official/regulatory facts are sourced from `OFFICIAL` or `EXCHANGE`.
- If both critical groups have at least one fact, a report can be published.
- If a non-critical source or detail page fails, the run completes with warnings and displays source/module/error summaries.
- If market facts are completely absent, the run fails and does not publish a normal report.
- If official/regulatory facts are completely absent, the run fails and does not publish a normal report.
- No real-source run silently falls back to fixture data.
