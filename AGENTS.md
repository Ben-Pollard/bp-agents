<!-- Style: headings tight, bullets terse, single lines. No multi-clause sentences. No filler words. -->

## Getting Started

- Use `uv sync` to install dependencies.
- Use `uv run <command>` to run Python commands (e.g. `uv run pytest`).
- Dev-only deps (ruff, pytest, pre-commit) live in the `dev` dependency group.

## Context

Read `CONTEXT.md` for the domain glossary and terminology conventions.

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels mapped to role strings. See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context repo. See `docs/agents/domain.md`.