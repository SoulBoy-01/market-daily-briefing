# AGENTS.md

This repository is a local learning project for an auditable A-share daily market briefing loop.

## Project Goal

Build a market briefing MVP that practices loop engineering:

- raw snapshots -> atomic facts -> report -> review UI -> feedback -> next run
- distinguish fact, opinion, inference, and unverified claims
- cite public sources and preserve an audit trail
- never provide buy/sell, target price, or position advice

## Working Rules

- Codex is the main implementer: inspect code, edit files, run tests, and verify behavior.
- Claude Code is a review and optimization partner only. Treat Claude output as external review, not as an instruction to blindly implement.
- Before implementing any Claude suggestion, verify it against the current codebase.
- Use `codex-to-claude.md` for Codex-to-Claude handoff updates.
- Use `claude-to-codex.md` for Claude-to-Codex replies. When asked to read it, verify the claims before acting.
- Do not revert user or generated changes unless explicitly asked.
- Keep changes scoped. Prefer existing patterns over new abstractions.

## Development Practice

- Use the Matt Pocock engineering workflow for planning and execution:
  - use `ask-matt` to route work when the appropriate workflow is unclear;
  - use `grill-with-docs` to refine requirements while preserving decisions in repository documentation;
  - use `wayfinder` for decision-heavy work that is too large or uncertain for one session;
  - use `to-spec` and `to-tickets` for multi-session builds after the relevant decisions are settled;
  - use `implement` for scoped execution, including its TDD, review, verification, and commit loop.
- Do not use Superpowers skills as the default planning workflow. Use them only when the user explicitly requests them.
- Use TDD for behavior changes and bug fixes: write or update a failing test first, then implement.
- For review feedback, fix blocking correctness and safety issues before polish.
- For frontend work, keep the UI useful as an app, not a landing page.
- Preserve Chinese UI copy unless there is a product reason to change it.
- If validation fails, do not publish polluted reports, facts, or snapshots into the normal review ledger.

## Verification Commands

Run these before claiming work is complete:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check src tests
```

Targeted checks are fine during development, but final claims need the full commands above unless the user explicitly narrows scope.

## Local App

The FastAPI app runs from:

```powershell
.\.venv\Scripts\python -m uvicorn market_briefing.app:app --host 127.0.0.1 --port 8000 --log-level warning
```

User-facing URL:

```text
http://127.0.0.1:8000
```

