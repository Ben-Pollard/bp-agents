Status: ready-for-agent

# 07 — Blocked state, Retries, Crash recovery

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001
- Glossary: `CONTEXT.md`

## What to Build

Three resilience behaviors:

1. **Retries** — Each stage has configurable retry limit. On `fail` outcome, retry with backoff. When retries exhausted, auto-transition to Blocked with `auto:` prefix reason.

2. **Blocked state management** — Blocked reason prefixed with `auto:` (retry limit, timeout) or `agent:` (agent-declared). Blocked ticket holds until human unblock (via CLI, in #06). Agent-declared block from #04; generalize reason prefixing here.

3. **Crash recovery** — On orchestrator restart: read SqliteSaver for all in-flight tickets. If sandbox still running, wait for completion. If sandbox gone, re-dispatch current stage. If outcome written but unapplied, process without re-dispatch. Detect and teardown orphaned sandboxes. Emit recovery event per ticket.

## Requirements

### User Stories

- As a **developer**, I want to unblock stalled tickets with instructions or code changes, so the system resumes without restarting from scratch.
- As a **developer**, I want the orchestrator to recover from crashes without re-running completed stages or incurring duplicate API cost, so I don't waste time or money.

### Domain Context

**Agent → Blocked → Agent Cycle (Max Retries)** (from reqs doc):

When a stage reaches its retry limit, the system transitions to Blocked. The developer unblocks via one of:
- Modifying code directly (e.g., in an interactive agent session on the branch).
- Providing instructions for an orchestrator-managed agent to resolve the conflict (clarifying an ambiguity, modifying ACs, sending a code review pass event).
- Requesting realignment with new ACs.

After unblocking, the orchestrator resumes at the blocked stage.

**Crash Recovery** (from reqs doc):

On orchestrator restart, the system:
- Reads persisted state to determine each in-flight ticket's current stage.
- If the sandbox for that stage is still running, waits for completion and reads the outcome.
- If the sandbox is gone (co-crashed), reschedules the current stage — not from the pipeline start. A ticket that completed TDD and was mid-code-review restarts at code review.
- If a stage outcome was written but not processed before crash, reads and transitions normally — no re-dispatch.
- Detects and tears down any orphaned sandboxes from the prior run.
- Emits a recovery event per ticket with the stage resumed.
- Resumes within one poll interval of restart.

**Stage Timeouts** (from reqs doc):

Each stage has a configurable timeout. On timeout, the orchestrator kills the agent, records a timeout event, and treats it as a failure (retry or block per stage config).

### Behavioral Scenarios

**Scenario: Max retries exhausted, human unblocks**

1. TDD agent fails (e.g., test failure after implementation). Orchestrator retries.
2. Retry 1 fails. Retry 2 fails. Retry limit of 3 reached.
3. Orchestrator transitions to Blocked with reason "auto: max retries (3) exhausted for TDD stage."
4. Developer investigates, modifies code on the feature branch directly.
5. Developer runs `symphony unblock hello-1 --note "Fixed import path"`.
6. Orchestrator transitions to Awaiting review (TDD was completed from prior retries; work is on branch).
7. Pipeline resumes from code review stage.

**Scenario: Orchestrator crashes mid-pipeline**

1. Ticket has completed TDD, is mid-code-review (Reviewing state). Orchestrator process dies.
2. Developer restarts orchestrator.
3. On startup, orchestrator reads persisted state: ticket hello-1 is in Reviewing, sandbox is gone (co-crashed).
4. Orchestrator detects orphaned sandbox, tears it down.
5. Orchestrator emits recovery event: "hello-1: recovered at Reviewing stage after crash."
6. Orchestrator re-dispatches code review agent for hello-1. TDD is NOT re-run.
7. Pipeline resumes normally.

**Scenario: Orchestrator crashes after stage outcome written but before transition**

1. TDD agent writes output contract. Orchestrator reads it but crashes before committing the changes and recording the state transition.
2. Developer restarts orchestrator.
3. Orchestrator reads persisted state: sees TDD outcome was written, state still Implementing.
4. Orchestrator commits the agent's changes, transitions to Awaiting review without re-dispatching TDD.
5. Pipeline continues from Awaiting review.

### Acceptance Criteria

- [AC-12] WHEN a stage exceeds its configured retry limit, stdout SHALL log `ticket <id>: blocked (auto: max retries exhausted)` and the sandbox orchestration layer SHALL report no new sessions for that ticket until unblocked.
- [AC-13] The blocked reason as reported by `symphony status <id>` and the front end SHALL be prefixed with `auto:` (retry limit, timeout) or `agent:` (agent-declared).
- [AC-17] WHEN the orchestrator restarts after a crash, stdout SHALL log a recovery event per in-flight ticket (`ticket <id>: recovered at <stage> after crash`).
- [AC-18] IF a ticket was in a stage and the sandbox orchestration layer reports no session for it on restart, THEN stdout SHALL log a re-dispatch for that stage only, and the sandbox orchestration layer SHALL report a new session — no session SHALL be reported for any earlier completed stage of that ticket.
- [AC-19] WHEN the orchestrator restarts and finds an unprocessed stage outcome, stdout SHALL log `ticket <id>: processing unapplied outcome from <stage>` and the sandbox orchestration layer SHALL report no new session for that stage.
- [AC-20] WHEN the orchestrator restarts and finds an orphaned session reported by the sandbox orchestration layer, stdout SHALL log `tearing down orphaned session for ticket <id>` and the sandbox orchestration layer SHALL report that session as torn down.
- [AC-26] WHEN a stage exceeds its configured timeout, stdout SHALL log `ticket <id>: stage <stage> timed out`, the sandbox orchestration layer SHALL report the session as stopped, and the timeout SHALL count as a failure for retry purposes.

### Architectural Constraints

**Decisions made** (from gap analysis):

- **ADR-0001**: LangGraph as pipeline engine — provides RetryPolicy, timeout, interrupt/resume, and checkpoint-based crash recovery.
- SQLite for state persistence via LangGraph's `SqliteSaver`.
- LangGraph checkpointer atomic at node boundaries; `outcome_path` is written-then-read with crash edge cases handled.
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- Error handling: three categories — transient retry (LangGraph), agent-declared block, timeout. Container always destroyed on failure.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- The orchestrator must resume in-flight tickets at the correct stage on restart without re-running completed stages or incurring duplicate API cost.
- All sandboxes must be torn down, even after an orchestrator crash (no orphaned sandboxes).
- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.

## This Ticket's Acceptance Criteria

- [ ] Stage exceeding retry limit (configurable) transitions to Blocked with `auto:` prefix reason
- [ ] Stage timeout kills agent session and counts as failure for retry purposes
- [ ] Timeout event logged with ticket ID, stage name, and duration
- [ ] Retry count resets per stage, not cumulative across pipeline
- [ ] Orchestrator restart recovers each in-flight ticket at its current stage
- [ ] Unapplied outcome written before crash is processed on restart without re-dispatch
- [ ] Orphaned sandboxes (no orchestrator process owns them) detected and torn down on restart
- [ ] Recovery events logged per ticket: `ticket <id>: recovered at <stage> after crash`
- [ ] Re-dispatch only for the crashed stage, never for earlier completed stages
- [ ] Still-running sandbox on restart is waited on, not duplicated

## Blocked by

- #05 Full pipeline