Status: ready-for-agent

# 09 — Multi-project config, Concurrency, Stage timeouts

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001
- Glossary: `CONTEXT.md`

## What to Build

Three scaling/operational behaviors:

1. **Multi-project config** — Orchestrator reads `BP_PROJECTS` env var, manages multiple project pipelines from a single process. Each project has its own tracker, repo, and workspace. Tickets show project prefix in logs and front-end. Cross-project ticket creation visible on next poll.

2. **Concurrency** — Configurable global limit (`BP_CONCURRENCY`) on concurrent agent sessions. Slot-based dispatch: when at limit, new ready tickets wait. Logs show `waiting for slot (<active>/<limit>)`.

3. **Stage timeouts** — Each stage has configurable timeout. On timeout, orchestrator kills agent session, logs timeout event, counts as failure for retry purposes.

## Requirements

### User Stories

- As a **developer**, I want to create tickets externally and have the orchestrator discover and dispatch them through a defined pipeline, so I focus on reviewing results, not managing agents.

### Domain Context

**Concurrency** (from reqs doc):

Configurable global limit on concurrent agent sessions across all projects. Defaults sensible for a single-developer machine.

**Stage Timeouts** (from reqs doc):

Each stage has a configurable timeout. On timeout, the orchestrator kills the agent, records a timeout event, and treats it as a failure (retry or block per stage config).

**Ticket Discovery** (from reqs doc):

The orchestrator discovers ready tickets by polling at a configurable interval. The poll interval is the maximum latency between a ticket becoming ready and dispatch. The tracker format is not prescribed — the orchestrator consumes tickets with ID, body, and state.

**Multiple Projects** (from reqs doc):

The orchestrator manages multiple projects concurrently from a single process. Each project has its own configuration (pipeline stages, ticket source, workspace). The dashboard shows all projects, filterable. An agent on project A can create a ticket in project B, which the orchestrator discovers via normal polling.

### Behavioral Scenarios

**Scenario: Concurrency limit reached**

1. Global concurrency limit is configured to 2. Two TDD agents are already running (sandbox orchestration reports two active sessions).
2. A third ticket becomes Ready. Orchestrator poll finds it.
3. No new sandbox session is created — sandbox orchestration still reports exactly two active sessions.
4. Stdout logs `ticket <id>: waiting for slot (2/2 active)`.
5. One of the running agents completes. Its session is reported as stopped.
6. On the next poll tick, the waiting ticket is dispatched — sandbox orchestration reports a new session.

**Scenario: Stage timeout**

1. TDD agent is dispatched with a 30-minute timeout.
2. Agent runs for 31 minutes without completing.
3. Stdout logs `ticket <id>: stage tdd timed out after 30m`.
4. Sandbox orchestration reports the agent's session as stopped.
5. The stage counts as a failure for retry purposes.
6. If retries remain, a new session for the same stage is created. If retries exhausted, ticket transitions to Blocked.

**Scenario: Cross-project ticket creation**

1. Orchestrator manages project-a and project-b. Both have ready tickets.
2. An agent working on a project-a ticket creates a new ticket in project-b's tracker (via its own tool calls).
3. On project-b's next poll tick, stdout logs the new ticket as found in project-b's ready queue.
4. The front-end shows the new ticket under project-b in Ready state.

### Acceptance Criteria

- [AC-25] WHILE the sandbox orchestration layer reports active sessions equal to the configured global limit, no new session SHALL be reported and stdout SHALL log `ticket <id>: waiting for slot (<active>/<limit> active)`.
- [AC-26] WHEN a stage exceeds its configured timeout, stdout SHALL log `ticket <id>: stage <stage> timed out`, the sandbox orchestration layer SHALL report the session as stopped, and the timeout SHALL count as a failure for retry purposes.
- [AC-38] WHEN an agent in project A creates a ticket in project B (via normal tracker operations), that ticket SHALL appear in project B's ready queue on the next poll tick, visible in the front end.

### Architectural Constraints

**Decisions made** (from gap analysis):

- **ADR-0001**: LangGraph — RetryPolicy for retries, timeout via LangGraph timeout policies.
- The orchestrator manages multiple projects concurrently from a single process. Each project has its own configuration.
- Environment variable configuration via `.env` + `python-dotenv`: `BP_CONCURRENCY`, `BP_PROJECTS`, per-project `BP_PROJECT_<NAME>_REPO` and `BP_PROJECT_<NAME>_PLANE_PROJECT_ID`.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

None specific beyond what's captured in ACs.

## This Ticket's Acceptance Criteria

- [ ] Concurrency limit enforced: no more than `BP_CONCURRENCY` concurrent agent sessions across all projects
- [ ] Ticket waiting for slot logs `waiting for slot (<active>/<limit>)` and dispatches when slot frees
- [ ] Stage timeout kills agent session and counts as failure for retry purposes
- [ ] Timeout event logged with ticket ID, stage name, and duration
- [ ] Multiple projects configured via `BP_PROJECTS` env var with per-project prefixes
- [ ] Tickets logged with `project=<name>` prefix in all log lines
- [ ] Cross-project ticket creation: agent-created ticket in project B discovered on project B's next poll
- [ ] Poll interval configurable — default matches a reasonable single-developer expectation

## Blocked by

- #05 Full pipeline
