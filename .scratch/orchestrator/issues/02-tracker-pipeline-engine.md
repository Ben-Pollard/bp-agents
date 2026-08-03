Status: ready-for-agent

# 02 — Tracker port + Pipeline engine skeleton

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0003
- Glossary: `CONTEXT.md`

## What to Build

Two connected pieces:

1. **Tracker port + Plane adapter** — `platform.tracker` ABC, `PlaneTracker` adapter in `workflows.sdd`, Plane in Compose. Orchestrator polls Plane for ready tickets, logs discovery counts per tick.

2. **Pipeline engine skeleton** — A LangGraph graph implementing the full ticket state machine (all 11 TicketState values) with stubbed agent nodes. Tickets discovered by the tracker flow through state transitions; every transition is logged to stdout with timestamp. State is persisted via SqliteSaver so a stopped pipeline resumes at its last state. Feature-level nested graph structure is in place.

No real agent dispatch — agent nodes are no-op stubs that advance state.

## Requirements

### User Stories

- As a **developer**, I want to create tickets externally and have the orchestrator discover and dispatch them through a defined pipeline, so I focus on reviewing results, not managing agents.
- As a **developer**, I want to see every stage of a ticket's progress — what's running, what completed, what failed — so I can monitor the system at a glance.

### Domain Context

**Pipeline** (from reqs doc):

Tickets flow through a fixed sequence of skill stages. Each stage is a separate dispatch. The orchestrator owns all git state — the agent reads and writes files in the sandbox, runs tests, and produces output. The orchestrator handles branching, committing, and merging deterministically.

Stages:

1. **TDD** — Orchestrator creates a feature branch from main. Agent writes code and tests, runs tests, exits with status and summary. Orchestrator commits the changes to the feature branch.
2. **Code review** — Orchestrator dispatches agent with the branch diff. Agent reviews the diff, produces feedback.
3. **Revision** — Orchestrator dispatches agent with feedback. Agent edits files to address feedback, exits with status and summary. Orchestrator commits revision changes.
4. **Verification** — Orchestrator dispatches agent. Agent runs tests in the workspace independently, exits with pass/fail.

The orchestrator passes carry-forward context between stages: TDD output includes summary → code review sees diff → revision sees feedback → verification confirms tests pass. The agent never touches git.

**Ticket States** (from reqs doc):

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

**Ticket Discovery** (from reqs doc):

The orchestrator discovers ready tickets by polling at a configurable interval. The poll interval is the maximum latency between a ticket becoming ready and dispatch. The tracker format is not prescribed — the orchestrator consumes tickets with ID, body, and state.

**Multiple Projects** (from reqs doc):

The orchestrator manages multiple projects concurrently from a single process. Each project has its own configuration (pipeline stages, ticket source, workspace). The dashboard shows all projects, filterable. An agent on project A can create a ticket in project B, which the orchestrator discovers via normal polling.

### Behavioral Scenarios

**Scenario: Normal end-to-end (auto-complete, human approves)** — skeleton (state transitions only, no real agents)

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

**Scenario: Cross-project ticket creation**

1. Orchestrator manages project-a and project-b. Both have ready tickets.
2. An agent working on a project-a ticket creates a new ticket in project-b's tracker (via its own tool calls).
3. On project-b's next poll tick, stdout logs the new ticket as found in project-b's ready queue.
4. The front-end shows the new ticket under project-b in Ready state.

### Acceptance Criteria

- [AC-27] WHEN a ticket changes state, stdout SHALL log the transition (`ticket <id>: <from-state> -> <to-state>`) with a timestamp and the transition SHALL appear in the ticket's state history in the front end.
- [AC-36] Stdout SHALL log each poll tick with the count of ready tickets found.
- [AC-37] Stdout SHALL log ticket dispatches with the project name (`project=<name> ticket=<id>`), and the front end SHALL group tickets by project.
- [AC-38] WHEN an agent in project A creates a ticket in project B (via normal tracker operations), that ticket SHALL appear in project B's ready queue on the next poll tick, visible in the front end.
- [AC-32] The front end SHALL list current ticket state for all tickets across all projects, filterable by project and state.

### Architectural Constraints

**Module: `platform.tracker`** — tracker port (workflow-agnostic)

```python
from abc import ABC, abstractmethod

class Tracker(ABC):
    """Abstract tracker port. Each workflow provides its own adapter and work-item model."""
    @abstractmethod
    async def list_ready(self, project: str) -> list[dict]: ...
    @abstractmethod
    async def get_item(self, item_id: str) -> dict | None: ...
    @abstractmethod
    async def update_state(self, item_id: str, state: str) -> None: ...
    @abstractmethod
    async def add_comment(self, item_id: str, body: str) -> None: ...
```

**Module: `workflows.sdd.tracker`** — Plane adapter (SDD workflow)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Ticket:
    """SDD work-item model. Plane work item UUID mapped to SDD TicketState."""
    id: str
    name: str
    description: str | None    # HTML body from Plane
    state: TicketState         # mapped from Plane state group
    project: str
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None

class PlaneTracker(Tracker):
    """Adapter for Plane.so self-hosted REST API. Implements platform's Tracker port.
    Maps Plane state groups to SDD TicketState."""
    def __init__(self, base_url: str, api_key: str, workspace_slug: str): ...
```

**Module: `workflows.sdd.graph`** — pipeline state

```python
class TicketPipelineState(TypedDict):
    ticket_id: str
    status: Literal["implementing", "awaiting_review", "reviewing", "awaiting_revision", "revising"]
    tdd_output: TddOutput | None
    review_output: ReviewOutput | None
    revision_output: RevisionOutput | None
    diff: str | None

class SDDFeatureState(TypedDict):
    feature_id: str
    project: str
    branch_name: str
    acs: list[dict]
    tickets: list[TicketSpec]
    ticket_states: dict[str, TicketPipelineState]
    current_stage: StageName
    blocked_reason: str | None
    blocked_at_stage: StageName | None
    minimizing_output: MinimizingOutput | None
    behavioral_verify_output: BehavioralVerifyOutput | None
    deterministic_gate_passed: bool | None
    contracts: list[StageContract]
    ac_changelog: list[ACChange]
    interventions: list[Intervention]
```

**Decisions made** (from gap analysis):

- **ADR-0001**: LangGraph as pipeline engine — free, MIT-licensed, self-hosted. Provides checkpointer, retry policy, timeout, interrupt/resume, and state streaming.
- **ADR-0003**: Plane.so as tracker — self-hosted project management with REST API for ticket CRUD and state management.
- SQLite for state persistence via LangGraph's `SqliteSaver`. Chosen over Postgres for single-machine self-host simplicity. Swappable.
- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- The tracker port is platform-level; `PlaneTracker` and `Ticket` are SDD adapters.

**Open Risks** (from gap analysis):

- **Plane state group mapping** — Plane state groups (`backlog`, `started`, `completed`, `cancelled`) don't cleanly map to our 11 ticket states. May need custom Plane states.
- **Feature-level AC tracking** — ACs are per-feature but tickets are per-Plane-item. How ACs flow from feature-level state into individual ticket contracts needs refinement during implementation.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

None specific to this slice.

## This Ticket's Acceptance Criteria

- [ ] `PlaneTracker.list_ready("project-name")` returns tickets from Plane API
- [ ] `PlaneTracker.update_state(ticket_id, state)` updates Plane state group
- [ ] Poll loop discovers ready tickets and logs count per tick (`ticket discovery: <N> ready`)
- [ ] Graph transition logs `ticket <id>: <from> -> <to>` with timestamp for every transition
- [ ] Stopped orchestrator resumes pipeline from last persisted state (SqliteSaver checkpoint)
- [ ] Multiple tickets flowing through the graph concurrently without interference
- [ ] Tickets grouped by project in logs and Plane UI

## Blocked by

- #01 Infrastructure + Contracts
