Status: ready-for-human

# 02 — Tracker port + Pipeline engine skeleton

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0003
- Glossary: `CONTEXT.md`

## What to Build

Two connected pieces:

1. **Tracker port + Redmine adapter** — `platform.tracker` ABC, `RedmineTracker` adapter in `workflows.sdd`, Redmine in Compose. Orchestrator polls Redmine for ready tickets, logs discovery counts per tick.

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

**Module: `workflows.sdd.tracker`** — Redmine adapter (SDD workflow)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Ticket:
    """SDD work-item model. Redmine issue ID mapped to SDD TicketState."""
    id: str
    name: str
    description: str | None
    state: TicketState
    project: str
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None

class RedmineTracker(Tracker):
    """Adapter for Redmine REST API. Implements platform's Tracker port.
    Maps Redmine issue statuses to SDD TicketState."""
    def __init__(self, base_url: str, api_key: str): ...
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
- **ADR-0003**: Redmine as tracker — self-hosted project management with REST API for ticket CRUD and state management. Replaced Plane.so which had unresolvable API and credential issues.
- SQLite for state persistence via LangGraph's `SqliteSaver`. Chosen over Postgres for single-machine self-host simplicity. Swappable.
- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- The tracker port is platform-level; `RedmineTracker` and `Ticket` are SDD adapters.

**Resolved Risks** (from previous Plane.so implementation):

- ~~Plane state group mapping~~ — Redmine issue statuses are fully customizable. Map SDD states directly to Redmine statuses via the admin UI or API.
- ~~Plane POST /issues/ 404 bug~~ — Redmine REST API supports full issue CRUD (GET, POST, PUT, DELETE) on `/issues.json`.
- ~~Plane UI credentials unknown~~ — Redmine default credentials (admin/admin) with forced password change on first login.

**Open Risks**:

- **Redmine status-to-state mapping** — Need to define which Redmine issue statuses map to which SDD TicketState values. Redmine defaults: New → Ready, In Progress → Implementing, Resolved → Awaiting review, etc. Custom statuses may be needed.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

None specific to this slice.

## This Ticket's Acceptance Criteria

- [ ] `RedmineTracker.list_ready("project-name")` returns issues from Redmine API
- [ ] `RedmineTracker.update_state(ticket_id, state)` updates Redmine issue status
- [ ] Poll loop discovers ready tickets and logs count per tick (`ticket discovery: <N> ready`)
- [ ] Graph transition logs `ticket <id>: <from> -> <to>` with timestamp for every transition
- [ ] Stopped orchestrator resumes pipeline from last persisted state (SqliteSaver checkpoint)
- [ ] Multiple tickets flowing through the graph concurrently without interference
- [ ] Tickets grouped by project in logs and Redmine UI

## Blocked by

- #01 Infrastructure + Contracts

## Outcome — ESCALATED (Review loop exceeded 3 rounds)

Implementation complete. TDD produced 73/73 passing tests (3 E2E skipped — need Redmine running), ruff clean. Review feedback narrowed across 3 rounds: 9 violations → 4 → 3.

**Resolved across rounds:**
- All 11 TicketState values reachable in graph
- Feature-level nested graph (`build_feature_pipeline`) with `SDDFeatureState`
- `Ticket.description` typed `str | None`, `Ticket.state` typed `TicketState`
- E2E test level created (`tests/e2e/`)
- Dead code removed (unreachable nodes)
- Survivable test assertions (call-count → behavioral)
- `revise_complete` routes to `awaiting_verification`
- `Tracker` ABC is workflow-agnostic (`list[dict]` return)
- `blocked` state reachable via `route_ticket`
- `e2e` pytest marker registered

**Remaining violations (round 3):**
1. `tracker.py:27-39` — `_parse_issue` maps Redmine status name to TicketState via name matching, but `DEFAULT_STATUS_MAP` uses status IDs. Status name "In Progress" → fallback to READY. Fix: reverse-lookup by status ID.
2. `FakeTracker`/`FakeTrackerReturns` return `list[Ticket]`/`Ticket` but `Tracker` ABC declares `list[dict]`/`dict`. Type mismatch across tests.
3. `test_sdd_graph.py:37-46` — 9-branch assertion test should be parametrised.

**Artefacts:**
- Implement: `.scratch/orchestrator/outcomes/implement-outcome.json`
- Review: `.scratch/orchestrator/outcomes/review-outcome.json`
- Reduction: `.scratch/orchestrator/outcomes/reduction-outcome.json` (not yet created — escalated before reduction step)
- QA: `.scratch/orchestrator/outcomes/verify-outcome.json` (not yet created — escalated before QA step)

The original implementation built a PlaneTracker adapter and LangGraph pipeline skeleton. All code-side ACs passed (60/60 unit tests, 3/3 integration tests, ruff clean). However, 3 ACs were blocked by Plane infrastructure issues:

1. **Plane API POST /issues/ returns 404** — commercial image bug, could not create tickets programmatically.
2. **Plane workspace owner credentials unknown** — could not sign into Plane web UI.
3. **Cross-project ticket creation** blocked by #1.

These blockers are resolved by migrating to Redmine. The existing PlaneTracker code will be replaced with a RedmineTracker adapter in a future session.

**Migration context:**
- Plane services (`plane`, `plane-db`, `plane-redis`, `rabbitmq`) removed from docker-compose.yml
- Redmine + redmine-db added in their place
- `.env.example` updated: `PLANE_*` → `REDMINE_*`
- ADR-0003 updated to reflect Redmine choice
- Volume `plane_db_data` removed, `redmine_db_data` added
- Implement outcomes: `.scratch/orchestrator/outcomes/implement-outcome.json`
- Review outcomes: `.scratch/orchestrator/outcomes/review-outcome.json`
- Reduction outcomes: `.scratch/orchestrator/outcomes/reduction-outcome.json`
- Verify outcomes: `.scratch/orchestrator/outcomes/verify-outcome.json`

Redmine default credentials: `admin` / `admin` (prompts for password change on first login).