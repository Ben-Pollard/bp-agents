# Architecture Gap Analysis

> Last updated: 2026-07-31
> Triggered by: `docs/requirements/orchestrator-agent-contract.md`

## Current State

Greenfield. No production code exists. The repo has scaffolding: empty `src/bp_agents/` package, OpenCode agent definitions in `opencode.json`, and a comprehensive requirements document for the orchestrator-agent pipeline. No ADRs, no architecture docs, no infrastructure.

The requirements define an orchestrator that discovers tickets from a tracker, dispatches coding agents through a pipeline of skill stages (TDD → code review → revision → minimizing-code → behavioral verification → deterministic verification → human approval → merge), persists state for crash recovery, and surfaces observability via Langfuse and stdout.

Target: single-developer, self-hosted, Docker Compose-managed. V1 scope. Behavioral verification deferred.

## Required Changes

Build from scratch:

- **Platform layer** — LangGraph runner, tracker port, sandbox port, opencode HTTP client, CLI framework. Reusable across workflows.
- **SDD workflow** — Specific LangGraph graph implementing the software development pipeline. Nested: feature graph contains ticket subgraphs.
- **Tracker adapter** — Plane.so REST API wrapper for ticket discovery and state updates.
- **Sandbox adapter** — `docker-py` wrapper with gVisor runtime, creating ephemeral containers per dispatch with HTTP forward proxy for egress enforcement.
- **Agent client** — `httpx`-based wrapper for opencode's HTTP API (create session, prompt, stream events).
- **Infrastructure** — Docker Compose managing orchestrator, Plane, Langfuse, SQLite, and egress proxy.

## Module Interfaces

### `platform.contracts` — shared data types

```python
from enum import StrEnum
from datetime import datetime
from typing import TypedDict, Literal, NotRequired

class TicketState(StrEnum):
    READY = "ready"
    IMPLEMENTING = "implementing"
    AWAITING_REVIEW = "awaiting_review"
    REVIEWING = "reviewing"
    AWAITING_REVISION = "awaiting_revision"
    REVISING = "revising"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    DONE = "done"

class StageName(StrEnum):
    TDD = "tdd"
    CODE_REVIEW = "code_review"
    REVISION = "revision"
    MINIMIZING_CODE = "minimizing_code"
    BEHAVIORAL_VERIFY = "behavioral_verify"
    DETERMINISTIC_GATE = "deterministic_gate"
    AWAIT_APPROVAL = "await_approval"
    MERGE = "merge"

class InterventionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REALIGN = "realign"
    UNBLOCK = "unblock"

class ACChange(TypedDict):
    timestamp: str
    actor: str
    ac_id: str
    change: Literal["ADDED", "MODIFIED", "REMOVED"]
    before: str | None
    after: str | None

class Intervention(TypedDict):
    timestamp: str
    actor: str
    type: InterventionType
    reason: str | None

class StageContract(TypedDict):
    stage: StageName
    direction: Literal["input", "output"]
    timestamp: str
    payload: dict
```

### `platform.tracker` — Plane adapter

```python
from abc import ABC, abstractmethod

@dataclass
class Ticket:
    id: str                    # Plane work item UUID
    name: str
    description: str | None    # HTML body from Plane
    state: TicketState         # mapped from Plane state group
    project: str
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None

class Tracker(ABC):
    @abstractmethod
    async def list_ready(self, project: str) -> list[Ticket]: ...
    @abstractmethod
    async def get_ticket(self, ticket_id: str) -> Ticket | None: ...
    @abstractmethod
    async def update_state(self, ticket_id: str, state: TicketState) -> None: ...
    @abstractmethod
    async def add_comment(self, ticket_id: str, body: str) -> None: ...

class PlaneTracker(Tracker):
    """Adapter for Plane.so self-hosted REST API. Maps Plane state groups to TicketState."""
    def __init__(self, base_url: str, api_key: str, workspace_slug: str): ...
```

### `platform.sandbox` — Docker/gVisor adapter

```python
from abc import ABC, abstractmethod

@dataclass
class SandboxConfig:
    image: str                  # e.g. "symphony-agent:latest"
    workspace_path: str         # host path to bind-mount
    skills_path: str            # host path for .agents/skills/
    runtime: str                # "runsc" (gVisor) or "" (default)
    env: dict[str, str]         # HTTP_PROXY, HTTPS_PROXY, outcome_path, etc.
    timeout_seconds: int
    mem_limit: str              # e.g. "512m"
    cpu_count: int

@dataclass
class SandboxSession:
    container_id: str
    port: int                   # exposed opencode serve port
    base_url: str               # "http://localhost:{port}"

class Sandbox(ABC):
    @abstractmethod
    async def create(self, config: SandboxConfig) -> SandboxSession: ...
    @abstractmethod
    async def is_running(self, container_id: str) -> bool: ...
    @abstractmethod
    async def destroy(self, container_id: str) -> None: ...
    @abstractmethod
    async def list_containers(self, label_filter: dict[str, str]) -> list[str]: ...

class DockerSandbox(Sandbox):
    """docker-py adapter with gVisor runtime support."""
    def __init__(self, docker_url: str = "unix://var/run/docker.sock"): ...
```

### `platform.agent_client` — OpenCode HTTP client

```python
@dataclass
class Session:
    session_id: str
    base_url: str

@dataclass
class PromptResult:
    prompt_id: str
    admitted: bool

class OpenCodeClient:
    """httpx wrapper for opencode serve HTTP API (OpenAPI 3.1)."""
    def __init__(self, base_url: str): ...

    async def create_session(self) -> Session: ...
    async def prompt(self, session: Session, text: str) -> PromptResult: ...
    async def stream_events(self, session: Session) -> AsyncIterator[dict]: ...
    async def session_status(self, session: Session) -> dict: ...
```

### `platform.cli` — CLI framework

```python
class CLI:
    """symphony CLI. Actions registered by workflows."""
    def __init__(self): ...
    def register_action(self, name: str, handler: Callable[[str, dict], None]): ...
    async def run(self, args: list[str]) -> None: ...

# Registered by SDD workflow:
#   symphony approve <ticket-id>
#   symphony reject <ticket-id> --reason "..."
#   symphony realign <ticket-id> --acs "..."
#   symphony unblock <ticket-id> [--note "..."]
#   symphony status [<ticket-id>]
```

### `workflows.sdd.contracts` — stage-specific types

```python
class TicketSpec(TypedDict):
    ticket_id: str
    name: str
    description: str
    acs: list[dict]              # [{"id": "AC-01", "text": "..."}]

class TddOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    test_results: dict           # {"passed": N, "failed": N, "skipped": N}
    concerns: list[str]

class ReviewOutput(TypedDict):
    spec_compliance: bool
    code_quality: dict[str, bool]
    test_quality: dict[str, bool]
    operational: bool
    violations: list[dict]       # [{"principle": "...", "file": "...", "issue": "..."}]
    review_notes: list[str]
    action: Literal["approved", "changes_requested"]

class RevisionOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    violations_addressed: list[dict]
    violations_pushed_back: list[dict]
    violations_unclear: list[dict]
    test_results: dict
    concerns: list[str]

class MinimizingOutput(TypedDict):
    modules_audited: int
    total_lines: int
    lines_eliminable: int
    reduction_table: list[dict]
    violations: list[dict]
    review_notes: str
    action: Literal["approved", "changes_requested", "escalate"]

class BehavioralVerifyOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    ac_results: list[dict]       # [{"id": "AC-01", "pass": bool, "evidence": "..."}]
    test_results: dict
```

### `workflows.sdd.graph` — pipeline state

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

### `docker-compose.yml` — service layout

```yaml
services:
  orchestrator:
    build: .
    env_file: .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./workspaces:/data/workspaces
    depends_on:
      - egress-proxy

  plane:
    image: makeplane/plane:latest
    # ... Plane's own Compose config, imported or referenced

  langfuse:
    image: langfuse/langfuse:latest
    # ... Langfuse's own Compose config

  egress-proxy:
    image: mitmproxy/mitmproxy:latest
    command: mitmweb --mode upstream:http://egress-proxy:8080 --allow-hosts "..."
    # allowlist: LLM API endpoints, package registries, MCP endpoints
```

### `.env.example` — secrets template

```bash
# Plane tracker
PLANE_BASE_URL=http://plane:8080
PLANE_API_KEY=plane_api_key_here
PLANE_WORKSPACE_SLUG=my-workspace

# Langfuse observability
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse:3000

# Model API (for orchestrator's own agent dispatches)
OPENROUTER_API_KEY=sk-or-...

# Projects
BP_PROJECTS=example-project
BP_PROJECT_EXAMPLE_PROJECT_REPO=/data/repos/example-project
BP_PROJECT_EXAMPLE_PROJECT_PLANE_PROJECT_ID=uuid-here

# Concurrency
BP_CONCURRENCY=2
```

### `state.json` — SQLite checkpointer schema

LangGraph's `SqliteSaver` manages its own schema. The orchestrator's persisted state is entirely within the checkpointer. No separate `state.json` needed.

## Decisions Made

- **ADR-0001**: LangGraph as pipeline engine — free, MIT-licensed, self-hosted. Provides checkpointer, retry policy, timeout, interrupt/resume, and state streaming.
- **ADR-0002**: gVisor/Docker sandbox with ephemeral containers per dispatch. `docker-py` adapter, `--runtime=runsc`. Fallback to hardened plain Docker if gVisor compatibility fails smoke test.
- **ADR-0003**: Plane.so as tracker — self-hosted project management with REST API for ticket CRUD and state management.
- **ADR-0004**: Langfuse for observability — agent traces, orchestrator traces, contract exchanges, and future eval platform. Single pane for all trace data.
- SQLite for state persistence via LangGraph's `SqliteSaver`. Chosen over Postgres for single-machine self-host simplicity. Swappable.
- JSON contracts via prompt embed (outbound) and `outcome_path` file (inbound). Skills write structured JSON; orchestrator reads and validates.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.
- Skills are copied from bp-agents `.agents/skills/` into workspace before dispatch. Skills retain `if git is available` git steps — git is unavailable in sandbox per egress policy.
- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- Environment variable configuration via `.env` + `python-dotenv`. Docker Compose injects into containers. No custom config file format.
- All services managed via Docker Compose: orchestrator, Plane, Langfuse, egress proxy.

## Decisions Deferred

- **Behavioral verification sandbox capabilities** — Browser, Docker-in-Docker, or app-as-Compose-service for E2E AC verification. Scope deferred due to complexity. Revisit when V1 pipeline is stable.
- **Data lifecycle / retention** — NFR calls for configurable retention pruning of trace and contract data. Deferred to V2.
- **E2B / Firecracker / Kata Containers** — Ruled out for V1. gVisor is the right point on the isolation spectrum for single-tenant self-host. Revisit only if a specific task demonstrates need.

## Affected Dimensions

| Dimension | Impact |
|---|---|
| Module decomposition | Platform/workflow split; 7 modules defined |
| Interface design | Concrete ABCs and TypedDicts for tracker, sandbox, agent_client, stage contracts |
| Seam placement | Tracker and sandbox are ports with adapters; agent_client and CLI are single-impl |
| Dependency direction | Nodes receive deps via Runtime[Context]; platform layer has no workflow dependency |
| Domain boundaries | Orchestrator ↔ Agent separated by JSON contracts and sandbox boundary |
| Data models | TicketState, StageName, stage output types, SDDFeatureState defined |
| Data flow | Push: orchestrator polls Plane → dispatches agent → reads outcome_path → updates Plane |
| State ownership | LangGraph checkpointer owns all state; orchestrator is sole writer |
| Storage technology | SQLite for state; Plane (Postgres internally) for ticket data |
| Protocol choices | REST (Plane), HTTP API (opencode), HTTP_PROXY (egress), JSON (contracts) |
| Message/event architecture | LangGraph state transitions are observable events; stdout logging per ACs |
| Integration patterns | HTTP API clients for external systems; adapters hide protocol details |
| Reliability | LangGraph RetryPolicy, timeout, interrupt/resume, checkpoint-based crash recovery |
| Consistency model | Checkpointer atomic at node boundaries; outcome_path is written-then-read with crash edge cases handled |
| Security | gVisor isolation, egress allowlist via proxy, no git or long-lived creds in sandbox |
| Error handling | Three categories: transient retry, agent-declared block, timeout |
| Observability | Structured stdout (operational), Langfuse (traces + evals) |
| Configuration | Environment variables via .env + python-dotenv |
| Build/CI/CD | Docker Compose manages all services; pre-commit via ruff + pytest |
| Deployment model | Docker Compose: orchestrator, Plane, Langfuse, egress proxy, SQLite |
| Test strategy | Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything) |
| Repository structure | Single repo for platform + workflows + infra; target projects external |

## Open Risks

- **gVisor compatibility with opencode** — opencode's tool loop (bash, file writes, LSP) may hit syscall gaps. Smoke test before committing. Fallback: hardened plain Docker.
- **Plane state group mapping** — Plane state groups (`backlog`, `started`, `completed`, `cancelled`) don't cleanly map to our 11 ticket states. May need custom Plane states.
- **opencode serve API stability** — The HTTP API is relatively new. Contract shape may change. Version-pin the opencode image.
- **Langfuse self-host complexity** — Needs to be verified as Docker Compose-able with minimal config.
- **Skill git steps in sandbox** — TDD/revision skills run `git add`/`git commit`. If git is blocked (AC-23) but still partially installed, edge cases may surface (git hangs vs clean error).
- **Feature-level AC tracking** — ACs are per-feature but tickets are per-Plane-item. How ACs flow from feature-level state into individual ticket contracts needs refinement during implementation.
- **Outcome_path convention** — Skills are instructed to write to `outcome_path`. If a skill doesn't respect this (e.g., writes somewhere else), the orchestrator gets no output. Mitigated by prompt instructions and verified in pipeline tests.