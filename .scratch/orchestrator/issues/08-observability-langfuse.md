Status: ready-for-agent

# 08 — Observability (Langfuse traces)

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0004
- Glossary: `CONTEXT.md`

## What to Build

Integrate Langfuse for observability. LangGraph callback pushes orchestrator-level traces to Langfuse. Agent session content at LLM-conversation granularity appears in Langfuse traces. Complete ticket history recoverable from ticket ID: every state transition, every contract exchanged, every human intervention, every AC changelog entry, every failure and retry. Langfuse runs in Docker Compose, accessible via documented URL.

No custom dashboard — Langfuse is the trace front-end; Plane is the ticket state front-end; CLI is the action surface.

## Requirements

### User Stories

- As a **developer**, I want to see every stage of a ticket's progress — what's running, what completed, what failed — so I can monitor the system at a glance.
- As a **developer**, I want to recover the full history of a ticket — state transitions, contracts, interventions, AC changes — from its ID, so I can understand what happened and why.

### Domain Context

**Traceability** (from reqs doc):

Given a ticket ID, the following is recoverable:
- Every state transition with timestamps.
- Every contract dispatched and returned.
- Every human intervention (approve, reject, realign, unblock) with who, when, and reason.
- Every AC redefinition event (what changed, when, by whom).
- Every failure and retry.
- Agent session content at LLM-conversation granularity.

This information is surfaced in a dashboard (implementation may adopt existing tools; what matters is the observable surface, not the tool choice).

**Observable Surface** (from reqs doc):

The system SHALL serve one or more web front-ends, startable via the service orchestration layer alongside the orchestrator. The README SHALL document how to discover and access each front-end.

Adopted tools (e.g., Jaeger for traces, Langfuse for eval data, custom dashboard for ticket state/actions) are front-ends. What matters is that the information and actions are accessible via a discoverable web interface.

### Behavioral Scenarios

**Scenario: Developer discovers and accesses front-ends** — Langfuse portion

1. Developer starts the orchestrator and all services as documented in the README.
2. Orchestrator and all front-end services start.
3. Developer follows the README to find the URL for each front-end.
4. Developer opens the trace front-end, sees agent session content at LLM-conversation level for a completed stage.

### Acceptance Criteria

- [AC-28] WHEN a contract is dispatched or returned, the full contract SHALL appear in stdout and be queryable in the ticket's history in the front end.
- [AC-30] WHEN a realignment occurs, the ticket's AC changelog (queryable in the front end) SHALL show what was added, modified, or removed, with timestamp and actor.
- [AC-31] Given a ticket ID, the front end SHALL return the complete history: state transitions, contracts, human interventions, AC changelog, failures, and retries.
- [AC-32] The front end SHALL list current ticket state for all tickets across all projects, filterable by project and state.

### Architectural Constraints

**Decisions made** (from gap analysis):

- **ADR-0004**: Langfuse for observability — agent traces, orchestrator traces, contract exchanges, and future eval platform. Single pane for all trace data.
- Structured stdout for operational logging; Langfuse for traces and evals.

**Decisions deferred** (from gap analysis):

- **Data lifecycle / retention** — NFR calls for configurable retention pruning of trace and contract data. Deferred to V2.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- Trace and contract data must be pruned after a configurable retention period. (Deferred to V2 per gap analysis.)

## This Ticket's Acceptance Criteria

- [ ] Langfuse receives traces from orchestrator (LangGraph callback integration)
- [ ] Agent session content visible in Langfuse traces at LLM-conversation granularity
- [ ] Complete ticket history recoverable from ticket ID: state transitions, contracts, interventions, AC changelog, failures, retries
- [ ] Langfuse accessible via documented URL in README
- [ ] Traces tagged with ticket ID and project for filtering
- [ ] Contract exchanges appear as spans within ticket traces

## Blocked by

- #05 Full pipeline
