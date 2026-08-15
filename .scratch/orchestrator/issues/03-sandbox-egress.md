Status: done

# 03 — Sandbox adapter + Egress proxy

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0002
- Glossary: `CONTEXT.md`

## What to Build

gVisor sandbox adapter (`platform.sandbox`) using `docker-py` as the container runtime interface (`--runtime=runsc`) for agent isolation. Ephemeral containers per dispatch, workspace bind-mounted from host. Egress proxy (mitmproxy) in Compose enforcing an allowlist: LLM API endpoints, package registries, MCP endpoints allowed; arbitrary internet and git remotes blocked. Blocked egress attempts logged to stdout. Git commands fail in sandbox.

No pipeline integration — create/destroy sandboxes programmatically, verify isolation and egress policy.

## Requirements

### User Stories

- As a **developer**, I want agent sandboxes to have controlled network access with no git credentials and unreadable API keys, so code stays local until I approve it.

### Domain Context

**Sandbox Egress Policy** (from reqs doc):

Agent sandboxes have controlled network access:

- **Allowed:** LLM API endpoints (OpenRouter, Anthropic, OpenAI, etc.), package registries (PyPI, npm), configured MCP endpoints (e.g., Context7).
- **Blocked:** Arbitrary internet, git remotes, and any destination not in the allowlist.

Blocked connection attempts are logged as observable events (destination, timestamp). The agent experiences a connection failure. Git credentials are never present in the sandbox; all git operations go through the orchestrator. LLM API keys are present in the sandbox but the agent cannot read them (delegated via OpenCode tool calls).

### Behavioral Scenarios

**Scenario: Sandbox attempts blocked network access**

1. TDD agent tries to fetch `https://example.com/arbitrary-data` during implementation.
2. Connection is blocked by egress policy — destination not in allowlist.
3. Agent sees connection failure in its session output.
4. Blocked attempt is logged to stdout: `blocked egress: https://example.com/arbitrary-data from ticket hello-1` with timestamp.
5. Agent exits with fail or continues (depends on agent handling of the error).

### Acceptance Criteria

- [AC-21] The configured egress allowlist (LLM API endpoints, package registries, MCP endpoints) SHALL be visible in stdout on startup. An agent sandbox SHALL be able to reach allowed destinations — observable by successful tool calls appearing in the agent session output.
- [AC-22] IF an agent attempts network access to a destination not in the allowlist, THEN stdout SHALL log `blocked egress: <destination> from ticket <id>` with a timestamp and the agent's session output SHALL show the connection failure.
- [AC-23] Any attempt by an agent to run a git command SHALL fail — observable by `git` returning an error in the agent session output. The orchestrator, not the agent, performs all git operations.

### Architectural Constraints

**Module: `platform.sandbox`** — gVisor adapter

```python
from abc import ABC, abstractmethod

@dataclass
class SandboxConfig:
    image: str                  # e.g. "opencode-agent:latest"
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

class GVisorSandbox(Sandbox):
    """gVisor sandbox using docker-py as the container runtime."""
    def __init__(self, docker_url: str = "unix://var/run/docker.sock"): ...
```

**Decisions made** (from gap analysis):

- **ADR-0002**: gVisor sandbox with ephemeral containers per dispatch. `docker-py` adapter, `--runtime=runsc`.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.
- Skills are copied from bp-agents `.agents/skills/` into workspace before dispatch. Skills retain `if git is available` git steps — git is unavailable in sandbox per egress policy.

**Open Risks** (from gap analysis):

- **gVisor compatibility with opencode** — opencode's tool loop (bash, file writes, LSP) may hit syscall gaps. Do not implement fallback.
- **Skill git steps in sandbox** — TDD/revision skills run `git add`/`git commit`. If git is blocked (AC-23) but still partially installed, edge cases may surface (git hangs vs clean error).

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- All sandboxes must be torn down, even after an orchestrator crash (no orphaned sandboxes).
- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.

## This Ticket's Acceptance Criteria

- [ ] `GVisorSandbox.create(config)` returns a running container with gVisor runtime (`runsc`)
- [ ] Sandbox can reach PyPI (package registry) — agent tool call `pip install` succeeds through proxy
- [ ] Sandbox cannot reach arbitrary internet — `curl https://example.com` fails; blocked egress logged to stdout
- [ ] Git commands (`git status`, `git add`, etc.) fail inside sandbox with a clear error
- [ ] `GVisorSandbox.destroy(container_id)` removes container
- [ ] `GVisorSandbox.list_containers(label_filter)` finds containers by label
- [ ] Egress allowlist is configurable and logged on startup

## Blocked by

- #01 Infrastructure + Contracts

## Outcome

All ACs pass. gVisor DNS limitation worked around by switching to default bridge.

- **gVisorSandbox.create** with `runtime=runsc` — running container on default bridge
- **PyPI reachable through proxy** — `pip install` succeeds via `http://172.17.0.1:8080` (host gateway)
- **Arbitrary internet blocked** — example.com → 403, proxy logs `blocked egress: <host> from ticket <unknown>`
- **Git commands fail** — `git` not installed in image, exit 127
- **Destroy / list_containers** — works correctly
- **Egress allowlist** — configurable via `MITMPROXY_ALLOWLIST` env var, logged on startup

**Root cause found:** gVisor netstack doesn't forward UDP on user-defined Docker bridge networks — Docker's embedded DNS (127.0.0.11) uses iptables DNAT rules gVisor doesn't apply. Upstream: [google/gvisor#7469](https://github.com/google/gvisor/issues/7469).

**Fix:** Sandboxes use Docker's default bridge (`network=""`) instead of `bp_agents` custom bridge. Proxy URL changed from `http://egress-proxy:8080` to `http://172.17.0.1:8080` (host gateway IP). E2E tests now exercise production config (runsc + default bridge).

**Test suite:** 97 passed, 3 skipped (Redmine E2E). Lint clean.

Outcome artifacts: `.scratch/orchestrator/outcomes/implement-outcome.json`, `review-outcome.json`, `reduction-outcome.json`, `verify-outcome.json`.
