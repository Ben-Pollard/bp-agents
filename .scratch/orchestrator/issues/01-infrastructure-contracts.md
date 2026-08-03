Status: in-progress

# 01 — Infrastructure + Contracts

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0002, ADR-0003, ADR-0004
- Glossary: `CONTEXT.md`

## What to Build

Scaffold the project: Docker Compose layout managing all services (orchestrator, Plane, Langfuse, egress proxy), `.env` configuration, all shared TypedDicts/enums/ABCs, and a README documenting how to start everything and access each front-end.

The orchestrator binary exists but does nothing except log "ready" and connect to its dependencies. No pipeline logic yet.

## Requirements

### User Stories

- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.

### Domain Context

**Observable Surface** (from reqs doc):

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

### Behavioral Scenarios

**Scenario: Developer discovers and accesses front-ends**

1. Developer starts the orchestrator and all services as documented in the README.
2. Orchestrator and all front-end services start.
3. Developer follows the README to find the URL for each front-end.
4. Developer opens a browser to the ticket-state front-end, sees all projects and tickets listed by current state.
5. Developer navigates to a specific ticket, sees its state history, contract exchanges, and intervention log.
6. Developer opens the trace front-end, sees agent session content at LLM-conversation level for a completed stage.

### Acceptance Criteria

- [AC-34] All front-ends SHALL be startable via the service orchestration layer alongside the orchestrator and SHALL be reachable by following the README.
- [AC-35] The README SHALL include discoverable instructions for accessing every front-end (URL, credentials if any, what each front-end shows).

### Architectural Constraints

**Module: `platform.contracts`** — generic contract primitives

```python
from typing import TypedDict, Literal

class StageContract(TypedDict):
    stage: str
    direction: Literal["input", "output"]
    timestamp: str
    payload: dict
```

**Module: `workflows.sdd.contracts`** — SDD-specific types and stage contracts

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

**Service layout: `docker-compose.yml`**

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

**Secrets template: `.env.example`**

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

**State persistence**

LangGraph's `SqliteSaver` manages its own schema. The orchestrator's persisted state is entirely within the checkpointer. No separate `state.json` needed.

**Architecture principles** (from `docs/architecture/principles.md`):

- **Adopt, don't build.** Prefer existing platforms (Plane, Langfuse, LangGraph) over custom solutions. Only build what bridges them.
- **Module boundaries are seams.** Only create ports when there are (or will be) multiple adapters. One adapter = no port.
- **Skills keep their git-availability check.** Skills work identically in and out of the orchestrator; git is simply absent in the sandbox.
- **Ephemeral sandboxes, persistent workspace.** Containers are per-dispatch; the workspace survives on the host across stages.
- **Env-first configuration.** Secrets and settings flow through environment variables. No custom config file format in V1.

**Decisions made** (from gap analysis):

- SDD-specific contracts (TicketState, StageName, InterventionType, ACChange, Intervention) live in `workflows.sdd`, not `platform.contracts`. Platform contracts are workflow-agnostic.
- Environment variable configuration via `.env` + `python-dotenv`. Docker Compose injects into containers. No custom config file format.
- All services managed via Docker Compose: orchestrator, Plane, Langfuse, egress proxy.
- Skills are copied from bp-agents `.agents/skills/` into workspace before dispatch. Skills retain `if git is available` git steps — git is unavailable in sandbox per egress policy.

### Testing Decisions

Repository structure: Single repo for platform + workflows + infra; target projects external.

### Non-Functional Requirements

- All services the system depends on must be managed via Docker Compose, not ad-hoc scripts.
- The system's README and startup experience must be sufficient for an agent (with a browser) to verify the system is working end-to-end without implementing workarounds or guessing at configuration.
- Dependency exploration during development must prioritize adopting existing software, querying capabilities via MCP, rolling back unfit choices, and maximizing the utility of chosen dependencies.
- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.

## This Ticket's Acceptance Criteria

- [ ] `docker compose up` starts all services (orchestrator, Plane, Langfuse, egress proxy) without errors
- [ ] `docker compose ps` shows all services as healthy/running
- [ ] All contract TypedDicts and enums in `platform.contracts` and `workflows.sdd.contracts` are importable without runtime errors
- [ ] README documents how to start services and access each front-end (URL, credentials if any, what each shows)
- [ ] `.env.example` contains all required variables with placeholder values

## Blocked by

None — can start immediately.
