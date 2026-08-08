# 01 — Code Organisation Refactor

Status: ready-for-agent

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- ADRs: 0001-0005
- Glossary: `CONTEXT.md`

## What Done Means

**Feature-level** (verbatim from the requirements doc):

> I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

**This ticket:** After this ticket, `platform/mcp/` and `platform/observability/` directories exist under `src/bp_agents/platform/` with `__init__.py` files, matching the requirements doc's code organisation layout, and all existing tests pass. No functional changes.

## What to Build

Create the directory structure for the two new platform modules. This is purely structural — no new code beyond `__init__.py` files. The layout must match the requirements doc exactly:

```
src/bp_agents/platform/mcp/
src/bp_agents/platform/observability/
```

The existing `src/bp_agents/platform/` layout already contains `dispatch.py`, `agent_client.py`, `agent_config.py`, `tracker.py`, and `sandbox/`. The new directories sit alongside these.

Verify that `uv run pytest` passes with zero regressions before and after the change.

## Requirements

### User Stories

None.

### Domain Context

Copy relevant domain context sections verbatim from the requirements doc. If none apply, write "None."

### Behavioral Scenarios

None.

### Acceptance Criteria

Copy the ACs this slice must satisfy, verbatim from the requirements doc. If none apply, write "None."

### Architectural Constraints

From `docs/architecture/gap-analysis-contract-broker.md`:

> - **New platform modules** — `platform/mcp/contract_broker.py`, `platform/observability/otel_receiver.py`. No `src/platform/` stub — everything under `src/bp_agents/platform/`.

From `docs/requirements/mcp-contract-broker-observability.md` (Code Organisation):

> ```
> src/bp_agents/
> ├── main.py
> ├── platform/
> │   ├── CONTEXT.md
> │   ├── runner.py
> │   ├── dispatch.py
> │   ├── agent_client.py
> │   ├── agent_config.py
> │   ├── tracker.py
> │   ├── mcp/
> │   │   └── contract_broker.py
> │   ├── observability/
> │   │   └── otel_receiver.py
> │   └── sandbox/
> │       ├── base.py
> │       ├── config.py
> │       ├── docker_sandbox.py
> │       └── egress.py
> └── workflows/
>     ├── CONTEXT.md
>     └── sdd/
>         ├── CONTEXT.md
>         ├── contracts.py
>         ├── graph.py
>         ├── state.py
>         ├── skill_configs.py
>         ├── tracker.py
>         └── nodes/
>             └── tdd.py
> ```

### Testing Decisions

None specific to this slice — existing test suite must pass unchanged.

### Non-Functional Requirements

None.

## This Ticket's Acceptance Criteria

- [ ] `src/bp_agents/platform/mcp/__init__.py` exists
- [ ] `src/bp_agents/platform/observability/__init__.py` exists
- [ ] No `src/platform/` or `src/workflows/` stub directories exist
- [ ] `uv run pytest` passes with zero failures
- [ ] No imports, function signatures, or behavior changed in any existing module

## Blocked by

None — can start immediately.