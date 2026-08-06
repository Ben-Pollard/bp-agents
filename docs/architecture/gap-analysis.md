# Architecture Gap Analysis

> Last updated: 2026-08-06
> Triggered by: `docs/requirements/orchestrator-agent-contract.md`

## Current State

Issue #04 complete: `OpenCodeClient` (httpx wrapper using `/api/session/*` endpoints), `TddNode` with env-var credential forwarding, Redmine tracker via `platform.tracker`, gVisor sandbox with egress proxy via `platform.sandbox`, LangGraph pipeline engine with SQLite checkpointer. ADRs 0001-0004 in place.

The requirements define an orchestrator that discovers tickets from a tracker, dispatches coding agents through a pipeline of skill stages (TDD → code review → revision → minimizing-code → behavioral verification → deterministic verification → human approval → merge), persists state for crash recovery, and surfaces observability via Langfuse and stdout.

Target: single-developer, self-hosted, Docker Compose-managed. V1 scope.

## Required Changes

Build from scratch (completed or in progress) plus credential security updates:

- **Platform layer** — LangGraph runner, tracker port, sandbox port, opencode HTTP client, CLI framework, agent config generation, dispatch lifecycle. Reusable across workflows.
- **SDD workflow** — Specific LangGraph graph implementing the software development pipeline. Nested: feature graph contains ticket subgraphs.
- **Tracker port** — Generic tracker ABC in platform. SDD workflow provides the Redmine adapter (`RedmineTracker`).
- **Sandbox adapter** — `docker-py` wrapper with gVisor runtime, creating ephemeral containers per dispatch with HTTP forward proxy for egress enforcement.
- **Agent client** — `httpx`-based wrapper for opencode's HTTP API. Must be rewritten from `/api/session/*` to `/session/*` endpoints with `auth_set`, `send_message`, `abort`.
- **Credential security** — Replace env-var credential forwarding with `PUT /auth/:id` API injection. Credentials never in env vars or files inside sandbox. No long-lived creds in sandbox (ADR-0005).
- **Per-dispatch config generation** — New `platform/dispatch.py` generates full `opencode.json` per skill dispatch, writes to workspace before container creation. Per-invocation model and tools set via `POST /session/{id}/message`.
- **Declarative skill configs** — New `workflows/sdd/skill_configs.py` with `SKILL_CONFIGS` dict mapping skill name → `AgentConfig(model, provider, permissions, tools, mcps)`.
- **Skills mount** — Replace `shutil.copytree` of skills with bind mount (read-only). No file copying per dispatch.
- **Infrastructure** — Docker Compose managing orchestrator, Redmine, Langfuse, SQLite, and egress proxy. One sandbox image with all MCP dependencies baked in.

## Module Interfaces

### `platform.contracts` — generic contract primitives

```python
from typing import TypedDict, Literal

class StageContract(TypedDict):
    stage: str
    direction: Literal["input", "output"]
    timestamp: str
    payload: dict
```

### `platform.tracker` — tracker port (workflow-agnostic)

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

### `platform.sandbox` — Docker/gVisor adapter

```python
from abc import ABC, abstractmethod

@dataclass
class SandboxConfig:
    image: str                  # e.g. "symphony-agent:latest"
    workspace_path: str         # host path to bind-mount
    skills_path: str            # host path for .agents/skills/ (bind-mounted read-only)
    runtime: str                # "runsc" (gVisor) or "" (default)
    env: dict[str, str]         # HTTP_PROXY, HTTPS_PROXY, outcome_path only — no credentials
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

class OpenCodeClient:
    """httpx wrapper for opencode serve HTTP API."""
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None): ...

    async def auth_set(self, provider_id: str, api_key: str) -> bool:
        """PUT /auth/{provider_id}  body: {"type": "api", "key": "..."}"""

    async def create_session(self) -> Session:
        """POST /session"""

    async def send_message(
        self,
        session: Session,
        parts: list[dict],                    # [{"type": "text", "text": "..."}]
        model: tuple[str, str],               # (provider_id, model_id)
        tools: dict[str, bool] | None = None, # {"bash": True, "read": True, "task": False}
    ) -> dict:
        """POST /session/{id}/message — blocks until agent turn complete.
        Body: {"model": {"providerID": P, "modelID": M}, "tools": {...}, "parts": [...]}"""

    async def session_status(self, session: Session) -> dict:
        """GET /session/{id}"""

    async def abort(self, session: Session) -> bool:
        """POST /session/{id}/abort — kill a running session"""

    async def close(self) -> None: ...
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

### `platform.agent_config` — per-skill agent configuration

```python
@dataclass
class AgentConfig:
    model: str                          # "openrouter/deepseek/deepseek-v4-flash"
    provider: str                       # "openrouter"
    permissions: dict                   # {"read": {"*.env": "deny", "*": "allow"}, "bash": {"sudo *": "deny", "*": "allow"}}
    tools: dict[str, bool]              # {"bash": True, "read": True, "edit": True, "task": False, "webfetch": False}
    mcps: dict[str, bool]               # {"playwright": True} — toggles only; MCP definitions baked into sandbox image

def to_opencode_json(config: AgentConfig, provider_defs: dict, mcp_defs: dict) -> dict:
    """Merges provider definitions, permissions, and MCP toggles into a valid opencode.json blob.
    Provider defs and MCP defs come from the sandbox image (hardcoded platform constants)."""
```

### `platform.dispatch` — full agent lifecycle

```python
PROVIDER_DEFINITIONS: dict = {
    "openrouter": {
        "name": "OpenRouter",
        "api": "https://openrouter.ai/api/v1",
        "options": {"apiKey": "{env:OPENROUTER_API_KEY}"},
        "models": {
            "deepseek/deepseek-v4-flash": {"name": "DeepSeek V4 Flash", "limit": {"context": 131072}},
        },
    },
}

MCP_DEFS: dict = {}  # populated when MCP deps baked into sandbox image

async def dispatch(
    sandbox: Sandbox,
    config: AgentConfig,
    skill: str,
    prompt: str,
    workspace: str,
    api_key: str,
) -> dict:
    """Full agent lifecycle. Idempotent — re-running with same workspace overwrites
    opencode.json and creates a fresh container.

    1. Write opencode.json to workspace root
    2. Create container (skills and workspace bind-mounted)
    3. Wait for GET /api/health → {"healthy": true}
    4. PUT /auth/{provider} inject creds
    5. POST /session create session
    6. POST /session/{id}/message send prompt (blocks until agent done)
    7. Read outcome_path from workspace, validate against stage contract
    8. Destroy container
    Returns validated outcome dict. Raises on failure — container always destroyed."""
```

### `workflows.sdd.skill_configs` — declarative skill → config mapping

```python
SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True, "task": False, "webfetch": False},
        mcps={},
    ),
    "code_review": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "deny"}},
        tools={"bash": True, "read": True, "edit": False, "task": False, "webfetch": False},
        mcps={},
    ),
    "revision": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True, "task": False, "webfetch": False},
        mcps={},
    ),
    "minimizing_code": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "edit": {"*": "deny"}},
        tools={"bash": True, "read": True, "edit": False, "task": False, "webfetch": False},
        mcps={},
    ),
    "behavioral_verify": AgentConfig(
        model="openrouter/anthropic/claude-sonnet-4",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "task": False, "webfetch": False},
        mcps={"playwright": True},
    ),
    "deterministic_gate": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": False, "task": False},
        mcps={},
    ),
}
```

### `workflows.sdd.contracts` — SDD-specific types and stage contracts

```python
from enum import StrEnum
from datetime import datetime
from typing import TypedDict, Literal, NotRequired

class TicketState(StrEnum):
    """SDD pipeline ticket lifecycle states."""
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
    """SDD pipeline skill stages."""
    TDD = "tdd"
    CODE_REVIEW = "code_review"
    REVISION = "revision"
    MINIMIZING_CODE = "minimizing_code"
    BEHAVIORAL_VERIFY = "behavioral_verify"
    DETERMINISTIC_GATE = "deterministic_gate"
    AWAIT_APPROVAL = "await_approval"
    MERGE = "merge"

class InterventionType(StrEnum):
    """SDD workflow human intervention actions."""
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

### `workflows.sdd.tracker` — Redmine adapter (SDD workflow)

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Ticket:
    """SDD work-item model. Redmine issue ID mapped to SDD TicketState."""
    id: str
    name: str
    description: str | None    # text body from Redmine
    state: TicketState         # mapped from Redmine issue status
    project: str
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None

class RedmineTracker(Tracker):
    """Adapter for Redmine REST API. Implements platform's Tracker port.
    Maps Redmine issue statuses to SDD TicketState."""
    def __init__(self, base_url: str, api_key: str): ...
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

  redmine:
    image: redmine:6
    ports:
      - "8082:3000"
    environment:
      REDMINE_DB_POSTGRES: redmine-db
    depends_on:
      redmine-db:
        condition: service_healthy

  redmine-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: redmine
      POSTGRES_PASSWORD: redmine_dev
      POSTGRES_DB: redmine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U redmine"]

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
# Redmine tracker
REDMINE_BASE_URL=http://redmine:3000
REDMINE_API_KEY=redmine_api_key_here
REDMINE_PROJECT_ID=my-project

# Langfuse observability
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://langfuse:3000

# Model API (for orchestrator to inject into sandbox via PUT /auth)
OPENROUTER_API_KEY=sk-or-...

# Projects
BP_PROJECTS=example-project
BP_PROJECT_EXAMPLE_PROJECT_REPO=/data/repos/example-project
BP_PROJECT_EXAMPLE_PROJECT_REDMINE_PROJECT_ID=identifier-here

# Concurrency
BP_CONCURRENCY=2
```

### `state.json` — SQLite checkpointer schema

LangGraph's `SqliteSaver` manages its own schema. The orchestrator's persisted state is entirely within the checkpointer. No separate `state.json` needed.

## Decisions Made

- **ADR-0001**: LangGraph as pipeline engine — free, MIT-licensed, self-hosted. Provides checkpointer, retry policy, timeout, interrupt/resume, and state streaming.
- **ADR-0002**: gVisor/Docker sandbox with ephemeral containers per dispatch. `docker-py` adapter, `--runtime=runsc`. Fallback to hardened plain Docker if gVisor compatibility fails smoke test.
- **ADR-0003**: Redmine as tracker — self-hosted project management with REST API for ticket CRUD and state management. Replaced Plane.so which had unresolvable API (POST /issues/ 404) and credential issues.
- **ADR-0004**: Langfuse for observability — agent traces, orchestrator traces, contract exchanges, and future eval platform. Single pane for all trace data.
- **ADR-0005**: No long-lived credentials in agent sandbox — LLM API keys are never stored in environment variables, files, or any persistent location inside the sandbox container. The orchestrator injects credentials into opencode's memory via `PUT /auth/:id` after container startup and before the prompt. Credentials exist only in the opencode server process for the duration of the sandbox session.
- SQLite for state persistence via LangGraph's `SqliteSaver`. Chosen over Postgres for single-machine self-host simplicity. Swappable.
- JSON contracts via prompt embed (outbound) and `outcome_path` file (inbound). Skills write structured JSON; orchestrator reads and validates.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.
- Skills are bind-mounted read-only from `.agents/skills/` into the sandbox. No file copying per dispatch. Skills retain `if git is available` git steps — git is unavailable in sandbox per egress policy.
- Full `opencode.json` generated per dispatch by the orchestrator and written to workspace root before container creation. Contains provider definitions, permission rules, and MCP toggles. No named agent profiles — model and tools are set per invocation via `POST /session/{id}/message`.
- `dispatch()` is the single platform function for the full agent lifecycle: config write → container create → health check (`GET /api/health`) → credential inject (`PUT /auth/:id`) → session create (`POST /session`) → prompt (`POST /session/{id}/message`, blocks) → outcome read → container destroy. Always destroys container before raising on failure.
- Per-invocation model selection via `model: {providerID, modelID}` in the message body. Per-invocation tool enable/disable via `tools: {tool_name: bool}` in the message body.
- `SKILL_CONFIGS` declarative dict in `workflows.sdd.skill_configs` maps skill name → `AgentConfig(model, provider, permissions, tools, mcps)`. Workflow nodes declare intent; platform's `dispatch()` realizes it.
- MCP dependencies baked into the sandbox image at build time. Per-dispatch opencode.json toggles `enabled: true/false` per skill. A single general-purpose sandbox image serves all skills.
- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- SDD-specific contracts (TicketState, StageName, InterventionType, ACChange, Intervention) live in `workflows.sdd`, not `platform.contracts`. Platform contracts are workflow-agnostic. The tracker port is platform-level; `RedmineTracker` and `Ticket` are SDD adapters.
- All services managed via Docker Compose: orchestrator, Redmine, Langfuse, egress proxy.

## Out of Scope for V1

- **Data lifecycle / retention** — NFR calls for configurable retention pruning of trace and contract data.
- **Multi-user deployment** — Single developer, local machine.

## Affected Dimensions

| Dimension | Impact |
|---|---|---|
| Module decomposition | Platform/workflow split; 10 modules defined (platform: contracts, tracker, sandbox, agent_client, agent_config, dispatch, cli; workflow: contracts, graph, skill_configs, tracker) |
| Interface design | Concrete ABCs, TypedDicts, dataclasses for tracker, sandbox, agent_client, AgentConfig, dispatch, stage contracts |
| Seam placement | Tracker port and sandbox are platform ports with workflow adapters. dispatch() is the seam between workflow (AgentConfig) and platform (container lifecycle). SDD-specific types live in workflows.sdd |
| Dependency direction | Nodes receive deps via Runtime[Context]; platform layer has no workflow dependency |
| Domain boundaries | Orchestrator ↔ Agent separated by JSON contracts and sandbox boundary. Credentials cross boundary via HTTP API only — never env or disk |
| Data models | TicketState, StageName, stage output types, SDDFeatureState, AgentConfig defined |
| Data flow | Push: orchestrator polls Redmine → generates opencode.json → dispatches agent via HTTP API → reads outcome_path → updates Redmine |
| State ownership | LangGraph checkpointer owns all state; orchestrator is sole writer |
| Storage technology | SQLite for state; Redmine (Postgres internally) for ticket data |
| Protocol choices | REST (Redmine), HTTP API (opencode serve: /session, /auth, /api/health), HTTP_PROXY (egress), JSON (contracts) |
| Message/event architecture | LangGraph state transitions are observable events; stdout logging per ACs |
| Integration patterns | HTTP API clients for external systems; adapters hide protocol details. Single dispatch() function encapsulates container lifecycle |
| Reliability | LangGraph RetryPolicy, timeout, interrupt/resume, checkpoint-based crash recovery. dispatch() always destroys container on failure |
| Consistency model | Checkpointer atomic at node boundaries; outcome_path is written-then-read with crash edge cases handled |
| Security | gVisor isolation, egress allowlist via proxy, credentials injected via PUT /auth (never in env vars or files inside sandbox), no git in sandbox, no long-lived creds in sandbox (ADR-0005) |
| Error handling | Three categories: transient retry (LangGraph), agent-declared block, timeout. Container always destroyed on failure |
| Observability | Structured stdout (operational), Langfuse (traces + evals) |
| Configuration | Environment variables via .env + python-dotenv for orchestrator. Per-dispatch opencode.json for agent sandbox |
| Build/CI/CD | Docker Compose manages all services; one sandbox image with MCP deps baked in; pre-commit via ruff + pytest |
| Deployment model | Docker Compose: orchestrator, Redmine, Langfuse, egress proxy, SQLite, one sandbox image |
| Test strategy | Node tests (mock dispatch) → platform tests (VCR-recorded opencode HTTP) → E2E tests (real everything) |
| Repository structure | Single repo for platform + workflows + infra; target projects external |

## Open Risks

- **gVisor compatibility with opencode** — opencode's tool loop (bash, file writes, LSP) may hit syscall gaps. Smoke test before committing. Fallback: hardened plain Docker.
- **Redmine status-to-state mapping** — Redmine default statuses (New, In Progress, Resolved, Closed, Rejected) don't cleanly map to our 11 ticket states. May need custom Redmine statuses.
- **opencode /session API stability** — The `/session/*` and `PUT /auth/:id` endpoints are newer than the `/api/*` surface. Contract shape may change. Version-pin the opencode npm package in the sandbox image.
- **opencode message endpoint blocking** — Assumes `POST /session/{id}/message` blocks until the agent turn is complete (tool loop handled server-side). If it returns after a single response, a polling fallback via `GET /session/{id}` is needed.
- **Langfuse self-host complexity** — Needs to be verified as Docker Compose-able with minimal config.
- **Skill git steps in sandbox** — TDD/revision skills run `git add`/`git commit`. If git is blocked (AC-23) but still partially installed, edge cases may surface (git hangs vs clean error).
- **Feature-level AC tracking** — ACs are per-feature but tickets are per-Redmine-item. How ACs flow from feature-level state into individual ticket contracts needs refinement during implementation.
- **Outcome_path convention** — Skills are instructed to write to `outcome_path`. If a skill doesn't respect this (e.g., writes somewhere else), the orchestrator gets no output. Mitigated by prompt instructions and verified in pipeline tests.
- **auth.set provider recognition** — `PUT /auth/:id` requires the provider to be defined in `opencode.json` for opencode to accept the key. Provider ID in the URL must match the provider key in the config.