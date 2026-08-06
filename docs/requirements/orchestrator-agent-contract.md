# Orchestrator-Agent Contract & Observability

> Last updated: 2026-07-31

## Problem Statement

A developer wants to describe work as tickets and have the system autonomously implement it — dispatching coding agents through a defined pipeline of skills (TDD, code review, revision, verification), merging approved work to main. Without a specified contract between orchestrator and agent, and without observable state throughout the pipeline, every agent session is a guess, every failure requires manual debugging, and the developer cannot trust the system to work without constant supervision.

The system replaces ad-hoc agent invocation with structured contracts: each skill stage receives an input contract, produces an output contract, and the orchestrator threads context between stages. Every state transition, contract exchange, human intervention, and AC redefinition is observable and recoverable from a ticket ID. Human approval flows through the orchestrator so merges are auditable system events.

## Solution

The orchestrator is a long-lived process that discovers tickets (created externally by the developer), drives each through a pipeline of skill stages (TDD → code review → revision → verification), and presents results for human approval before merging to main. The developer interacts primarily as an observer-curator: watching progress, approving/rejecting at gates, unblocking stalled tickets, and requesting realignment when requirements change.

The orchestrator persists enough state to recover from crashes without re-running completed stages or incurring duplicate API cost. Agents run in sandboxes with a defined egress policy — LLM APIs, package registries, and configured MCP endpoints are reachable; arbitrary internet and git remotes are not. Long-lived git credentials never enter the sandbox. LLM API keys are injected into opencode's process memory via HTTP API — never present in environment variables, files, or any agent-accessible location inside the sandbox.

## User Stories

- As a **developer**, I want to create tickets externally and have the orchestrator discover and dispatch them through a defined pipeline, so I focus on reviewing results, not managing agents.
- As a **developer**, I want to see every stage of a ticket's progress — what's running, what completed, what failed — so I can monitor the system at a glance.
- As a **developer**, I want to approve or reject completed work through the orchestrator, so merges to main are auditable system events.
- As a **developer**, I want to unblock stalled tickets with instructions or code changes, so the system resumes without restarting from scratch.
- As a **developer**, I want to request realignment when requirements change mid-ticket, so the system reworks from new ACs and records the change.
- As a **developer**, I want the orchestrator to recover from crashes without re-running completed stages or incurring duplicate API cost, so I don't waste time or money.
- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.
- As a **developer**, I want to recover the full history of a ticket — state transitions, contracts, interventions, AC changes — from its ID, so I can understand what happened and why.
- As a **developer**, I want agent sandboxes to have controlled network access with no git credentials and unreadable API keys, so code stays local until I approve it.

## Domain Context

### Pipeline

Tickets flow through a fixed sequence of skill stages. Each stage is a separate dispatch. The orchestrator owns all git state — the agent reads and writes files in the sandbox, runs tests, and produces output. The orchestrator handles branching, committing, and merging deterministically.

Stages:

1. **TDD** — Orchestrator creates a feature branch from main. Agent writes code and tests, runs tests, exits with status and summary. Orchestrator commits the changes to the feature branch.
2. **Code review** — Orchestrator dispatches agent with the branch diff. Agent reviews the diff, produces feedback.
3. **Revision** — Orchestrator dispatches agent with feedback. Agent edits files to address feedback, exits with status and summary. Orchestrator commits revision changes.
4. **Verification** — Orchestrator dispatches agent. Agent runs tests in the workspace independently, exits with pass/fail.

The orchestrator passes carry-forward context between stages: TDD output includes summary → code review sees diff → revision sees feedback → verification confirms tests pass. The agent never touches git.

### Ticket States

| State | Meaning | Orchestrator Behavior |
|---|---|---|
| **Ready** | Ticket exists, eligible for dispatch | Dispatches TDD agent when slot available |
| **Implementing** | TDD agent running | Monitors for completion, timeout, or crash |
| **Awaiting review** | TDD complete, code review pending | Dispatches code review agent |
| **Reviewing** | Code review agent running | Monitors |
| **Awaiting revision** | Review complete, feedback to address | Dispatches revision agent with feedback |
| **Revising** | Revision agent running | Monitors |
| **Awaiting verification** | Revision complete, verification pending | Dispatches verification agent |
| **Verifying** | Verification agent running | Monitors |
| **Awaiting approval** | All stages passed, waiting for human | Presents branch for review; no further dispatch |
| **Blocked** | Cannot proceed (retries exhausted, dependency unmet, or agent-declared) | No dispatch until human unblocks |
| **Done** | Human approved, merged to main | Workspace teardown |

Every state transition is an observable event.

### Contracts

Each skill stage has a defined input contract and output contract. The input contract contains at minimum: skill name, ticket body, and carry-forward context from prior stages. The output contract contains at minimum: outcome status and structured data for the next stage. Contracts are observable — dispatched and returned in the trace.

Outcome statuses:
- `complete` — stage succeeded, advance to next stage.
- `blocked` — agent cannot proceed; transition to Blocked with reason.
- `fail` — transient error; retry per stage config.

### Human Interventions

Four actions, available via CLI and dashboard:

- **Approve** — merge branch to main, transition to Done.
- **Reject** — reject with reason; transition back to TDD with reason in contract.
- **Realign** — modify ACs, transition back to TDD; record a redefinition event with AC diff, timestamp, and who triggered it.
- **Unblock** — provide resolution (code change, instructions, review override), transition back to the stage where blocked.

Redefinition events are stored per ticket as a changelog. Later analysis can correlate AC churn with escalation/blocking events.

Blocked is triggered when:
- A stage exhausts its retry limit (automatic).
- An agent declares it cannot proceed in its output contract (agent-declared).

The reason field distinguishes the source.

### Agent → Blocked → Agent Cycle (Max Retries)

When a stage reaches its retry limit, the system transitions to Blocked. The developer unblocks via one of:
- Modifying code directly (e.g., in an interactive agent session on the branch).
- Providing instructions for an orchestrator-managed agent to resolve the conflict (clarifying an ambiguity, modifying ACs, sending a code review pass event).
- Requesting realignment with new ACs.

After unblocking, the orchestrator resumes at the blocked stage.

### Approval and Code Delivery

Agent-written code stays local until approval. The orchestrator maintains a local clone. The agent's feature branch is visible in the developer's git client for review. On approval, the orchestrator merges to main locally. Pushing to a remote is optional and post-approval. The orchestrator is the sole process that can merge to main.

### Sandbox Egress Policy

Agent sandboxes have controlled network access:

- **Allowed:** LLM API endpoints (OpenRouter, Anthropic, OpenAI, etc.), package registries (PyPI, npm), configured MCP endpoints (e.g., Context7).
- **Blocked:** Arbitrary internet, git remotes, and any destination not in the allowlist.

Blocked connection attempts are logged as observable events (destination, timestamp). The agent experiences a connection failure. Git credentials are never present in the sandbox; all git operations go through the orchestrator. LLM API keys are injected into opencode's process memory via HTTP API — never present in environment variables, files, or any agent-accessible location inside the sandbox.

### Crash Recovery

On orchestrator restart, the system:
- Reads persisted state to determine each in-flight ticket's current stage.
- If the sandbox for that stage is still running, waits for completion and reads the outcome.
- If the sandbox is gone (co-crashed), reschedules the current stage — not from the pipeline start. A ticket that completed TDD and was mid-code-review restarts at code review.
- If a stage outcome was written but not processed before crash, reads and transitions normally — no re-dispatch.
- Detects and tears down any orphaned sandboxes from the prior run.
- Emits a recovery event per ticket with the stage resumed.
- Resumes within one poll interval of restart.

### Traceability

Given a ticket ID, the following is recoverable:
- Every state transition with timestamps.
- Every contract dispatched and returned.
- Every human intervention (approve, reject, realign, unblock) with who, when, and reason.
- Every AC redefinition event (what changed, when, by whom).
- Every failure and retry.
- Agent session content at LLM-conversation granularity.

This information is surfaced in a dashboard (implementation may adopt existing tools; what matters is the observable surface, not the tool choice).

### Observable Surface

The system SHALL serve one or more web front-ends, startable via the service orchestration layer alongside the orchestrator. The README SHALL document how to discover and access each front-end.

Front-ends expose:
- Current ticket state for all tickets across all projects, filterable by project and state.
- State transition history per ticket.
- Contract exchanges per stage dispatch.
- Agent session content at LLM-conversation level.
- Human intervention history per ticket.
- AC changelog per ticket.
- Action surface: approve, reject, realign, unblock.

Adopted tools (e.g., Jaeger for traces, Langfuse for eval data, custom dashboard for ticket state/actions) are front-ends. What matters is that the information and actions are accessible via a discoverable web interface.

### Concurrency

Configurable global limit on concurrent agent sessions across all projects. Defaults sensible for a single-developer machine.

### Stage Timeouts

Each stage has a configurable timeout. On timeout, the orchestrator kills the agent, records a timeout event, and treats it as a failure (retry or block per stage config).

### Ticket Discovery

The orchestrator discovers ready tickets by polling at a configurable interval. The poll interval is the maximum latency between a ticket becoming ready and dispatch. The tracker format is not prescribed — the orchestrator consumes tickets with ID, body, and state.

### Multiple Projects

The orchestrator manages multiple projects concurrently from a single process. Each project has its own configuration (pipeline stages, ticket source, workspace). The dashboard shows all projects, filterable. An agent on project A can create a ticket in project B, which the orchestrator discovers via normal polling.

## Behavioral Scenarios

### Scenario: Normal end-to-end (auto-complete, human approves)

1. A ticket exists in Ready state: "Write a function that returns 'hello world' and a test."
2. Orchestrator poll finds the ticket, creates feature branch `feat/hello-1` from main, dispatches TDD agent with input contract (skill: tdd, ticket body).
3. TDD agent writes code and tests to the workspace, runs tests, exits with output contract `{status: complete, summary: "..."}`.
4. Orchestrator commits the agent's changes to `feat/hello-1`, transitions to Awaiting review.
5. Orchestrator dispatches code review agent with input contract (skill: requesting-code-review, diff of `main..feat/hello-1`, summary).
6. Code review agent reviews the diff, exits with `{status: complete, feedback: null}` (no issues).
7. Orchestrator transitions to Awaiting revision, then to Awaiting verification.
8. Orchestrator dispatches verification agent with input contract (skill: verification-before-completion, workspace at `feat/hello-1`).
9. Verification agent runs test suite independently, exits with `{status: complete, tests_pass: true}`.
10. Orchestrator transitions to Awaiting approval. Developer's git client shows `feat/hello-1` branch.
11. Developer reviews diff, runs `symphony approve hello-1`.
12. Orchestrator merges `feat/hello-1` to main, transitions to Done, tears down workspace.

### Scenario: Review finds issues, agent revises

1. TDD completes, orchestrator commits changes, dispatches code review agent.
2. Code review agent exits with `{status: complete, feedback: "Edge case missing in test for empty input"}`.
3. Orchestrator transitions to Awaiting revision, dispatches revision agent with feedback in contract.
4. Revision agent edits files to add the missing test case, exits with `{status: complete, summary: "..."}`.
5. Orchestrator commits revision changes, transitions to Awaiting verification. Verification dispatched.
6. Verification exits with `{status: complete, tests_pass: true}`. Pipeline continues to Awaiting approval.

### Scenario: Max retries exhausted, human unblocks

1. TDD agent fails (e.g., test failure after implementation). Orchestrator retries.
2. Retry 1 fails. Retry 2 fails. Retry limit of 3 reached.
3. Orchestrator transitions to Blocked with reason "auto: max retries (3) exhausted for TDD stage."
4. Developer investigates, modifies code on the feature branch directly.
5. Developer runs `symphony unblock hello-1 --note "Fixed import path"`.
6. Orchestrator transitions to Awaiting review (TDD was completed from prior retries; work is on branch).
7. Pipeline resumes from code review stage.

### Scenario: Human rejects with reason

1. Ticket reaches Awaiting approval. Developer reviews the diff.
2. Developer finds the implementation missed a requirement, runs `symphony reject hello-1 --reason "No validation on null input as per AC-04"`.
3. Orchestrator records rejection event, transitions to Implementing (back to TDD).
4. Orchestrator creates a fresh TDD branch, dispatches TDD agent with rejection reason in contract.
5. Agent implements the fix. Orchestrator commits. Pipeline runs through all stages again.

### Scenario: Human requests realignment

1. Ticket reaches Awaiting approval. Developer realizes the ACs are wrong.
2. Developer runs `symphony realign hello-1` with updated ACs (AC-04 added, AC-05 modified).
3. Orchestrator records redefinition event: `AC-04 ADDED, AC-05 MODIFIED: inputs over 1MB must raise ValidationError`. Timestamp and actor recorded.
4. Orchestrator transitions to Implementing, creates a fresh branch, dispatches TDD agent with new ACs in contract.
5. Pipeline runs from start with updated requirements.

### Scenario: Agent declares blocked

1. TDD agent discovers it cannot proceed — the ticket references a function signature from another module that hasn't been implemented yet.
2. Agent exits with `{status: blocked, reason: "Module utils.validators not yet implemented — needed by this ticket"}`.
3. Orchestrator transitions to Blocked with reason "agent: Module utils.validators not yet implemented."
4. Developer works on the blocking ticket or provides an implementation of the missing module.
5. Developer runs `symphony unblock hello-1`.
6. Orchestrator resumes at Implementing.

### Scenario: Orchestrator crashes mid-pipeline

1. Ticket has completed TDD, is mid-code-review (Reviewing state). Orchestrator process dies.
2. Developer restarts orchestrator.
3. On startup, orchestrator reads persisted state: ticket hello-1 is in Reviewing, sandbox is gone (co-crashed).
4. Orchestrator detects orphaned sandbox, tears it down.
5. Orchestrator emits recovery event: "hello-1: recovered at Reviewing stage after crash."
6. Orchestrator re-dispatches code review agent for hello-1. TDD is NOT re-run.
7. Pipeline resumes normally.

### Scenario: Orchestrator crashes after stage outcome written but before transition

1. TDD agent writes output contract. Orchestrator reads it but crashes before committing the changes and recording the state transition.
2. Developer restarts orchestrator.
3. Orchestrator reads persisted state: sees TDD outcome was written, state still Implementing.
4. Orchestrator commits the agent's changes, transitions to Awaiting review without re-dispatching TDD.
5. Pipeline continues from Awaiting review.

### Scenario: Sandbox attempts blocked network access

1. TDD agent tries to fetch `https://example.com/arbitrary-data` during implementation.
2. Connection is blocked by egress policy — destination not in allowlist.
3. Agent sees connection failure in its session output.
4. Blocked attempt is logged to stdout: `blocked egress: https://example.com/arbitrary-data from ticket hello-1` with timestamp.
5. Agent exits with fail or continues (depends on agent handling of the error).

### Scenario: Developer discovers and accesses front-ends

1. Developer starts the orchestrator and all services as documented in the README.
2. Orchestrator and all front-end services start.
3. Developer follows the README to find the URL for each front-end.
4. Developer opens a browser to the ticket-state front-end, sees all projects and tickets listed by current state.
5. Developer navigates to a specific ticket, sees its state history, contract exchanges, and intervention log.
6. Developer opens the trace front-end, sees agent session content at LLM-conversation level for a completed stage.

### Scenario: Concurrency limit reached

1. Global concurrency limit is configured to 2. Two TDD agents are already running (sandbox orchestration reports two active sessions).
2. A third ticket becomes Ready. Orchestrator poll finds it.
3. No new sandbox session is created — sandbox orchestration still reports exactly two active sessions.
4. Stdout logs `ticket <id>: waiting for slot (2/2 active)`.
5. One of the running agents completes. Its session is reported as stopped.
6. On the next poll tick, the waiting ticket is dispatched — sandbox orchestration reports a new session.

### Scenario: Stage timeout

1. TDD agent is dispatched with a 30-minute timeout.
2. Agent runs for 31 minutes without completing.
3. Stdout logs `ticket <id>: stage tdd timed out after 30m`.
4. Sandbox orchestration reports the agent's session as stopped.
5. The stage counts as a failure for retry purposes.
6. If retries remain, a new session for the same stage is created. If retries exhausted, ticket transitions to Blocked.

### Scenario: Cross-project ticket creation

1. Orchestrator manages project-a and project-b. Both have ready tickets.
2. An agent working on a project-a ticket creates a new ticket in project-b's tracker (via its own tool calls).
3. On project-b's next poll tick, stdout logs the new ticket as found in project-b's ready queue.
4. The front-end shows the new ticket under project-b in Ready state.

## Acceptance Criteria

> Ubiquitous and state-driven ACs describing standing invariants with no specific trigger (AC-13, AC-21, AC-23, AC-31, AC-32, AC-33, AC-36, AC-37) carry no scenario tag — they are always-true properties, not extracted from a walkthrough.

### Ticket lifecycle

- [AC-01] (Scenario: Normal end-to-end) WHEN a ticket is in Ready state and an agent slot is available, the sandbox orchestration layer SHALL report a new session for that ticket and stdout SHALL log `ticket <id>: dispatching tdd` with the contract contents.
- [AC-02] (Scenario: Normal end-to-end) WHEN a TDD agent returns an output contract with `status: complete`, stdout SHALL log `ticket <id>: implementing -> awaiting-review`, `git log` on the feature branch SHALL show the orchestrator's commit of the agent's changes, and the ticket SHALL appear in the Awaiting review state in the front end and CLI.
- [AC-03] (Scenario: Review finds issues, agent revises) WHEN a code review agent returns an output contract containing feedback, stdout SHALL log `ticket <id>: reviewing -> awaiting-revision` with the feedback, the feedback SHALL appear in the ticket's history in the front end, and the sandbox orchestration layer SHALL report a new session for the revision agent.
- [AC-04] (Scenario: Review finds issues, agent revises) WHEN a revision agent returns `status: complete`, stdout SHALL log `ticket <id>: revising -> awaiting-verification`, `git log` on the feature branch SHALL show the orchestrator's commit of revision changes, and the sandbox orchestration layer SHALL report a new session for the verification agent.
- [AC-05] (Scenario: Normal end-to-end) WHEN a verification agent returns an output contract with `tests_pass: true`, stdout SHALL log `ticket <id>: verifying -> awaiting-approval`, the ticket SHALL appear in the Awaiting approval state in the front end and CLI, and the sandbox orchestration layer SHALL report no new sessions for that ticket.
- [AC-06] (Scenario: Normal end-to-end) WHEN a human approves a ticket via CLI or the action surface, stdout SHALL log `ticket <id>: approved by <user>` and `git log` on main SHALL show the feature branch's commits merged.
- [AC-07] (Scenario: Normal end-to-end) WHEN a ticket reaches Done, stdout SHALL log `ticket <id>: done, tearing down` and the sandbox orchestration layer SHALL report the ticket's sessions as torn down.

### Human interventions

- [AC-08] (Scenario: Human rejects with reason) WHEN a human rejects a ticket with a reason, stdout SHALL log `ticket <id>: rejected by <user>, reason: <reason>`, the rejection SHALL appear in the ticket's history in the front end, and the sandbox orchestration layer SHALL report a new TDD session.
- [AC-09] (Scenario: Human requests realignment) WHEN a human realigns a ticket with updated ACs, stdout SHALL log a redefinition event containing the AC diff and actor, and the ticket's AC changelog (visible in the front end) SHALL contain a new entry with the same diff.
- [AC-10] (Scenario: Max retries exhausted, human unblocks) WHEN a human unblocks a ticket, stdout SHALL log `ticket <id>: unblocked by <user>` and the sandbox orchestration layer SHALL report a new session for the stage where the ticket was blocked.
- [AC-11] (Scenario: Agent declares blocked) WHEN an agent exits with `status: blocked`, stdout SHALL log `ticket <id>: blocked, reason: <reason>` and the ticket SHALL appear in the Blocked state in the front end and CLI.

### Blocked and retries

- [AC-12] (Scenario: Max retries exhausted, human unblocks) WHEN a stage exceeds its configured retry limit, stdout SHALL log `ticket <id>: blocked (auto: max retries exhausted)` and the sandbox orchestration layer SHALL report no new sessions for that ticket until unblocked.
- [AC-13] The blocked reason as reported by `symphony status <id>` and the front end SHALL be prefixed with `auto:` (retry limit, timeout) or `agent:` (agent-declared).

### Contracts

- [AC-14] (Scenario: Normal end-to-end) WHEN a stage is dispatched, the input contract (containing skill name, ticket body, and carry-forward context) SHALL appear in stdout and be visible in the ticket's history in the front end.
- [AC-15] (Scenario: Normal end-to-end) WHEN an agent completes a stage, the output contract (containing status and structured data) SHALL appear in stdout and be visible in the ticket's history in the front end.
- [AC-16] (Scenario: Normal end-to-end) The carry-forward context from stage N's output contract SHALL appear in stage N+1's input contract, visible when the ticket's contract history is queried in the front end.

### Crash recovery

- [AC-17] (Scenario: Orchestrator crashes mid-pipeline) WHEN the orchestrator restarts after a crash, stdout SHALL log a recovery event per in-flight ticket (`ticket <id>: recovered at <stage> after crash`).
- [AC-18] (Scenario: Orchestrator crashes mid-pipeline) IF a ticket was in a stage and the sandbox orchestration layer reports no session for it on restart, THEN stdout SHALL log a re-dispatch for that stage only, and the sandbox orchestration layer SHALL report a new session — no session SHALL be reported for any earlier completed stage of that ticket.
- [AC-19] (Scenario: Orchestrator crashes after stage outcome written but before transition) WHEN the orchestrator restarts and finds an unprocessed stage outcome, stdout SHALL log `ticket <id>: processing unapplied outcome from <stage>` and the sandbox orchestration layer SHALL report no new session for that stage.
- [AC-20] (Scenario: Orchestrator crashes mid-pipeline) WHEN the orchestrator restarts and finds an orphaned session reported by the sandbox orchestration layer, stdout SHALL log `tearing down orphaned session for ticket <id>` and the sandbox orchestration layer SHALL report that session as torn down.

### Sandbox egress and git isolation

- [AC-21] The configured egress allowlist (LLM API endpoints, package registries, MCP endpoints) SHALL be visible in stdout on startup. An agent sandbox SHALL be able to reach allowed destinations — observable by successful tool calls appearing in the agent session output.
- [AC-22] (Scenario: Sandbox attempts blocked network access) IF an agent attempts network access to a destination not in the allowlist, THEN stdout SHALL log `blocked egress: <destination> from ticket <id>` with a timestamp and the agent's session output SHALL show the connection failure.
- [AC-23] Any attempt by an agent to run a git command SHALL fail — observable by `git` returning an error in the agent session output. The orchestrator, not the agent, performs all git operations.
- [AC-24] (Scenario: Normal end-to-end) WHEN a human approves a ticket, `git log` on main SHALL show the merged commits — the merge was performed by the orchestrator, not by any agent.

### Concurrency and timeouts

- [AC-25] (Scenario: Concurrency limit reached) WHILE the sandbox orchestration layer reports active sessions equal to the configured global limit, no new session SHALL be reported and stdout SHALL log `ticket <id>: waiting for slot (<active>/<limit> active)`.
- [AC-26] (Scenario: Stage timeout) WHEN a stage exceeds its configured timeout, stdout SHALL log `ticket <id>: stage <stage> timed out`, the sandbox orchestration layer SHALL report the session as stopped, and the timeout SHALL count as a failure for retry purposes.

### Observability and traceability

- [AC-27] (Scenario: Normal end-to-end) WHEN a ticket changes state, stdout SHALL log the transition (`ticket <id>: <from-state> -> <to-state>`) with a timestamp and the transition SHALL appear in the ticket's state history in the front end.
- [AC-28] (Scenario: Normal end-to-end) WHEN a contract is dispatched or returned, the full contract SHALL appear in stdout and be queryable in the ticket's history in the front end.
- [AC-29] (Scenario: Human rejects with reason) WHEN a human performs an approve, reject, realign, or unblock action, stdout SHALL log the action with user, timestamp, and reason, and the action SHALL appear in the ticket's intervention history in the front end.
- [AC-30] (Scenario: Human requests realignment) WHEN a realignment occurs, the ticket's AC changelog (queryable in the front end) SHALL show what was added, modified, or removed, with timestamp and actor.
- [AC-31] Given a ticket ID, the front end SHALL return the complete history: state transitions, contracts, human interventions, AC changelog, failures, and retries.
- [AC-32] The front end SHALL list current ticket state for all tickets across all projects, filterable by project and state.
- [AC-33] The CLI or action surface SHALL accept and confirm approve, reject, realign, and unblock commands for a given ticket ID, and the confirmation SHALL appear in stdout.
- [AC-34] (Scenario: Developer discovers and accesses front-ends) All front-ends SHALL be startable via the service orchestration layer alongside the orchestrator and SHALL be reachable by following the README.
- [AC-35] (Scenario: Developer discovers and accesses front-ends) The README SHALL include discoverable instructions for accessing every front-end (URL, credentials if any, what each front-end shows).

### Ticket discovery and multi-project

- [AC-36] Stdout SHALL log each poll tick with the count of ready tickets found.
- [AC-37] Stdout SHALL log ticket dispatches with the project name (`project=<name> ticket=<id>`), and the front end SHALL group tickets by project.
- [AC-38] (Scenario: Cross-project ticket creation) WHEN an agent in project A creates a ticket in project B (via normal tracker operations), that ticket SHALL appear in project B's ready queue on the next poll tick, visible in the front end.

### Approval and code delivery

- [AC-39] (Scenario: Normal end-to-end) WHILE a ticket is in any state other than Done, `git log` on any remote SHALL NOT show the feature branch's commits.
- [AC-40] (Scenario: Normal end-to-end) WHEN a ticket reaches Awaiting approval, the feature branch SHALL appear in `git branch` output in the local repository and the branch name SHALL be visible in the ticket's status in the front end.

## Non-Functional Requirements

- The orchestrator must resume in-flight tickets at the correct stage on restart without re-running completed stages or incurring duplicate API cost.
- All sandboxes must be torn down, even after an orchestrator crash (no orphaned sandboxes).
- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.
- Trace and contract data must be pruned after a configurable retention period.
- The system's README and startup experience must be sufficient for an agent (with a browser) to verify the system is working end-to-end without implementing workarounds or guessing at configuration.
- Dependency exploration during development must prioritize adopting existing software, querying capabilities via MCP, rolling back unfit choices, and maximizing the utility of chosen dependencies.
- All services the system depends on must be managed via Docker Compose, not ad-hoc scripts.

## Out of Scope

- Ticket creation (grill-requirements, grill-architecture, to-prd, to-issues) — tickets exist before the orchestrator sees them.
- Skill authoring (TDD, code-review, revision, verification) — skills are external definitions the system loads.
- Model training or fine-tuning.
- Remote or multi-user deployment — single developer, local machine.
- Multi-tenant operation.
- Auto-approval — the verification stage always runs, and human approval is always required before merge.

## Priority

**Critical.** Defines the fundamental contract between orchestrator and agents, the ticket lifecycle, human interaction model, crash recovery, and observability. All other requirements depend on this.

## Changelog

- **2026-08-06**: Updated credential model — LLM API keys are injected into opencode's process memory via HTTP API, never present in environment variables, files, or any agent-accessible location inside the sandbox. Replaces previous "present but unreadable" language per ADR-0005.
