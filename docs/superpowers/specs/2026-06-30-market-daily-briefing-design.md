# A-Share Daily Market Briefing MVP Design

Date: 2026-06-30
Status: Ready for user review

## Purpose

Build a small project for learning loop engineering through a daily A-share / domestic stock market briefing system.

The first version is a market overview product with an explicit audit and feedback loop. It summarizes indices, sectors, policy and regulatory updates, major market news, and risk points. It verifies sources, separates facts from opinions and inferences, and does not provide buy/sell advice.

## Learning Scope

The project should eventually exercise three loop-engineering layers:

1. Data collection, verification, and report generation.
2. Human feedback on each report and section.
3. Automated run reliability, logs, reruns, and later alerts.

The MVP starts with an end-to-end local system, but its architecture reserves space for all three loops.

## Chosen Approach

Use an audit-core-first approach.

The primary system boundary is:

```text
Sources -> Raw Snapshots -> Atomic Fact Ledger -> Briefing Draft -> Markdown/HTML Report -> Section Feedback -> Next Run Context
```

This keeps the project from becoming only a report writer. Every generated claim should be traceable to captured material, and every feedback item should be reusable by the next run.

## Architecture

The MVP uses a Python backend with a lightweight local web dashboard.

Backend modules:

1. `source collectors`: collect structured market data and web/news/policy material.
2. `snapshot store`: save raw source material for audit.
3. `fact ledger`: convert source material into atomic facts with source metadata.
4. `briefing generator`: generate Markdown and HTML reports from the fact ledger.
5. `feedback loop`: store report-level and section-level feedback for later runs.
6. `dashboard API/UI`: expose reports, facts, snapshots, run logs, module settings, and feedback.

Storage combines files and SQLite:

- Files store raw snapshots, Markdown reports, HTML reports, and exported fact ledgers.
- SQLite stores facts, runs, reports, feedback, module configuration, source snapshot indexes, and report metadata.

The MVP does not include scheduled jobs, email/Feishu push, complex announcement parsing, or stock recommendations. These are extension points.

## Report Types

The system supports two report rhythms:

1. `after_close`: the main post-market report.
2. `pre_open_update`: the next-morning supplement.

The MVP may run both manually from the dashboard. Later versions can add scheduling.

## Configurable Modules

The default scope is a standard market overview, with module-level switches. Each report records the modules that were enabled during its run.

Default `after_close` modules:

- `market_indices`: major indices such as SSE Composite, SZSE Component, ChiNext, STAR 50.
- `market_temperature`: market turnover, advance/decline counts, limit-up/limit-down counts, as available.
- `sector_moves`: top and bottom industry/theme sector moves.
- `policy_regulation`: official policy, regulatory, and exchange updates.
- `major_news`: major market news, with media treated as news background rather than official policy proof.
- `risk_points`: risk points grounded in the fact ledger.

Default `pre_open_update` modules:

- `overnight_context`: overnight external market context, exchange rates, commodities, or related signals, using a small source set in the MVP.
- `policy_news_delta`: new policy, regulatory, and major news updates since the post-market report.
- `today_watchpoints`: watchpoints and risks for the current trading day, with clear fact/inference boundaries.

Out of MVP scope:

- Buy/sell advice.
- Stock recommendations.
- Target prices.
- Position sizing.
- Portfolio tracking.
- Deep stock announcement parsing.
- Dragon Tiger List analysis.
- Social media sentiment.
- Automatic push notifications.

## Sources and Verification

The MVP uses a restrained three-layer source strategy:

1. Structured market data via an adapter layer such as AkShare.
2. Official policy and regulatory sources such as CSRC and stock exchanges.
3. A small set of media/news sources for background market news.

Verification rules:

- Every factual claim must have a source URL and publication time when available.
- Policy, regulatory, and exchange-rule claims should rely on official sources.
- Media can be used as background for `major_news`.
- Media reports that describe regulatory changes must remain background or `unverified` until an official source is found.
- Third-party data wrappers are not treated as final authority. Runs should record the adapter source and fetched time, and exchange-related figures should preserve their stated source where possible.

Fact classifications:

- `fact`: a verifiable claim with a clear source.
- `opinion`: a named media, institution, or analyst view.
- `inference`: a system-generated conclusion derived from specific facts.
- `unverified`: insufficiently sourced or unclear material. It should not appear as a main conclusion.

The report must not output stock recommendations, target prices, position advice, or direct buy/sell language.

## Atomic Fact Ledger

Reports can only cite facts that have entered the fact ledger.

Suggested `AtomicFact` fields:

- `fact_id`: stable identifier.
- `report_date`: trading/report date.
- `report_type`: `after_close` or `pre_open_update`.
- `module`: source module.
- `claim`: one verifiable statement.
- `classification`: `fact`, `opinion`, `inference`, or `unverified`.
- `source_name`: human-readable source name.
- `source_url`: source URL.
- `source_type`: official, exchange, media, data API, or other.
- `published_at`: source publication time when available.
- `fetched_at`: collection time.
- `confidence`: `high`, `medium`, or `low`.
- `raw_snapshot_path`: local snapshot file path.
- `derived_from_fact_ids`: fact ids used by an inference.
- `used_in_sections`: report sections that cite the fact.

Suggested file layout:

```text
data/raw/YYYY-MM-DD/<run_id>/...
reports/YYYY-MM-DD/<report_type>/briefing.md
reports/YYYY-MM-DD/<report_type>/briefing.html
reports/YYYY-MM-DD/<report_type>/fact_ledger.json
data/market_briefing.sqlite
```

## Report Generation and LLM Boundary

The system produces two layers:

1. `fact ledger`: the auditable source of truth.
2. `readable briefing`: Markdown report rendered to HTML.

The default generator is template based. If an API key and provider are configured, an LLM can rewrite or summarize based only on:

- The current fact ledger.
- The previous feedback summary for the same report type.
- Fixed writing rules.

LLM constraints:

- Each section must cite existing `fact_id` values.
- LLM output must not introduce numbers, dates, organizations, or policy conclusions absent from the ledger.
- `fact`, `opinion`, and `inference` require distinct wording or labels.
- `risk_points` must cite supporting facts and cannot become investment advice.
- If a module lacks data, the report should say the data is unavailable rather than invent content.
- If validation fails, the system falls back to the template report and records the reason in the run log.

Provider design:

- `template` or `none` must work without an API key.
- `openai_compatible` can be added as a configurable provider.
- Additional providers can be added later behind the same interface.

## Loop Dashboard

The dashboard is a local lightweight web UI organized around a Loop First layout.

Primary functions:

- Select report date and report type.
- Manually trigger `after_close` and `pre_open_update`.
- View the HTML report and access the Markdown file.
- Inspect fact ledger entries, source metadata, confidence, and raw snapshots.
- Inspect run logs and module statuses.
- Enable or disable modules per report type.
- Submit and review feedback.

First-screen structure:

- Main area: current report, summary, sections, and fact markers.
- Side area: section feedback, fact ledger list, source/snapshot details, and next-run context.

Feedback model:

- Report-level score from 1 to 5.
- Section-level tags such as `missing_key_point`, `weak_source`, `too_verbose`, `too_much_opinion`, `insufficient_risk`, and `unclear_citation`.
- One short note per section.
- A generated `feedback_summary` that becomes context for the next run of the same report type.

No MVP support for multi-user accounts, permissions, real-time market screens, or drag-and-drop report editing.

## Error Handling and Observability

Errors should be visible but should not silently corrupt reports.

If a source or module fails:

- Continue the run when possible.
- Mark the affected section as `data_unavailable`.
- Record failure reason, retry count, exception summary, and affected module in the run log.

Run records should include:

- `run_id`, `report_date`, `report_type`, and trigger mode.
- Enabled modules.
- Source statuses.
- Number of snapshots, facts, and generated sections.
- Generation mode: template or LLM.
- Validation results.
- Output paths.
- Feedback status.

The MVP includes dashboard-visible run logs and local log files. Later automation can add alerts.

## Testing Strategy

Required test categories:

- Unit tests for fact classification, source confidence, report validation, and feedback summary generation.
- Integration tests using fixture snapshots for `raw -> facts -> report -> feedback`.
- Mock LLM provider tests that verify unsupported claims are rejected and the system falls back to templates.
- Smoke tests that start the local app, generate both report types, and open them from the dashboard.

## MVP Milestones

1. `Project skeleton + storage`
   Create the Python backend, lightweight frontend, SQLite schema, file layout, configuration, and local startup path. The app should create runs, reports, and feedback records without real data.

2. `Audit pipeline with fixtures`
   Use fixed fixtures to run `raw snapshot -> atomic facts -> fact ledger -> Markdown/HTML`, including validators.

3. `Real source adapters`
   Add a small real source set: major index/sector structured data, official policy/regulatory sources, and a small set of news sources.

4. `Loop Dashboard`
   Implement the Loop First dashboard for triggering runs, reading reports, inspecting facts/snapshots/logs, switching modules, and submitting feedback.

5. `Two report rhythms + optional LLM`
   Run both `after_close` and `pre_open_update`. Template generation works by default. Configured LLM generation runs through validation and fallback.

## MVP Acceptance Criteria

- Manual triggers can generate both `after_close` and `pre_open_update`.
- Each run outputs Markdown and HTML.
- Every report fact can be traced to the fact ledger and a raw snapshot.
- Policy/regulatory facts come from official sources or are clearly marked as media background or unverified.
- The dashboard can submit a section tag, section note, and report-level score.
- The next run of the same report type can read the previous feedback summary.
- A single module failure does not silently distort the report; the dashboard and logs show the failure.

## Current Project Context

At design time, the project directory contained only:

- `work/`
- `outputs/`

The directory was not a git repository. If git is initialized later, `.superpowers/` should be ignored because it contains brainstorming companion runtime files.
