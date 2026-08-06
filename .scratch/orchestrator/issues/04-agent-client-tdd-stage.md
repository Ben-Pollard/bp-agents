Status: done

# 04 — Agent client, Dispatch, Agent config, Skills mount, TDD stage

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0002, ADR-0005
- Glossary: `CONTEXT.md`

## What to Build

OpenCode HTTP client (`platform.agent_client`) wrapping `httpx` for opencode's HTTP API: create session, inject credentials via `PUT /auth/:id`, send message with per-invocation model/tools config, check session status, abort. Per-dispatch agent config generation (`platform.agent_config` + `platform.dispatch`): declarative `AgentConfig` and `SKILL_CONFIGS` dict mapping skill name to configuration, `to_opencode_json()` to generate `opencode.json`, and `dispatch()` for the full agent lifecycle (config write → container create → health check → credential inject → session create → message → outcome read → container destroy). Skills bind-mounted read-only into sandbox — no file copying per dispatch.

Then the TDD pipeline node — the first real agent dispatch. TDD node: uses `dispatch()`, commits agent's work to feature branch of target project. Both input and output contracts logged to stdout. Agent-declared block (`status: BLOCKED` in output) transitions ticket to Blocked.

After this slice, a ticket flows Ready → Implementing → Awaiting Review with real agent work committed to a feature branch of the target project and the correct ticket status visible in Redmine.

## Requirements

### User Stories

- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.
- As a **developer**, I want agent sandboxes to have controlled network access with no git credentials and unreadable API keys, so code stays local until I approve it.

### Domain Context

**Contracts** (from reqs doc):

Each skill stage has a defined input contract and output contract. The input contract contains at minimum: skill name, ticket body, and carry-forward context from prior stages. The output contract contains at minimum: outcome status and structured data for the next stage. Contracts are observable — dispatched and returned in the trace.

Outcome statuses:
- `complete` — stage succeeded, advance to next stage.
- `blocked` — agent cannot proceed; transition to Blocked with reason.
- `fail` — transient error; retry per stage config.

**Pipeline** (from reqs doc) — TDD stage:

1. **TDD** — Orchestrator creates a feature branch from main. Agent writes code and tests, runs tests, exits with status and summary. Orchestrator commits the changes to the feature branch.

**Sandbox Egress Policy** (from reqs doc):

Agent sandboxes have controlled network access:
- **Allowed:** LLM API endpoints (OpenRouter, Anthropic, OpenAI, etc.), package registries (PyPI, npm), configured MCP endpoints (e.g., Context7).
- **Blocked:** Arbitrary internet, git remotes, and any destination not in the allowlist.

LLM API keys are injected into opencode's process memory via HTTP API — never present in environment variables, files, or any agent-accessible location inside the sandbox.

### Behavioral Scenarios

**Scenario: Normal end-to-end (auto-complete, human approves)** — TDD portion

1. A ticket exists in Ready state: "Write a function that returns 'hello world' and a test."
2. Orchestrator poll finds the ticket, creates feature branch `feat/hello-1` from main, dispatches TDD agent with input contract (skill: tdd, ticket body).
3. TDD agent writes code and tests to the workspace, runs tests, exits with output contract `{status: complete, summary: "..."}`.
4. Orchestrator commits the agent's changes to `feat/hello-1`, transitions to Awaiting review.

**Scenario: Agent declares blocked**

1. TDD agent discovers it cannot proceed — the ticket references a function signature from another module that hasn't been implemented yet.
2. Agent exits with `{status: blocked, reason: "Module utils.validators not yet implemented — needed by this ticket"}`.
3. Orchestrator transitions to Blocked with reason "agent: Module utils.validators not yet implemented."
4. Developer works on the blocking ticket or provides an implementation of the missing module.
5. Developer runs `symphony unblock hello-1`.
6. Orchestrator resumes at Implementing.

**Scenario: Sandbox attempts blocked network access**

1. TDD agent tries to fetch `https://example.com/arbitrary-data` during implementation.
2. Connection is blocked by egress policy — destination not in allowlist.
3. Agent sees connection failure in its session output.
4. Blocked attempt is logged to stdout: `blocked egress: https://example.com/arbitrary-data from ticket hello-1` with timestamp.
5. Agent exits with fail or continues (depends on agent handling of the error).

### Acceptance Criteria

- [AC-01] WHEN a ticket is in Ready state and an agent slot is available, the sandbox orchestration layer SHALL report a new session for that ticket and stdout SHALL log `ticket <id>: dispatching tdd` with the contract contents.
- [AC-02] WHEN a TDD agent returns an output contract with `status: complete`, stdout SHALL log `ticket <id>: implementing -> awaiting-review`, `git log` on the feature branch SHALL show the orchestrator's commit of the agent's changes, and the ticket SHALL appear in the Awaiting review state in the front end and CLI.
- [AC-11] WHEN an agent exits with `status: blocked`, stdout SHALL log `ticket <id>: blocked, reason: <reason>` and the ticket SHALL appear in the Blocked state in the front end and CLI.
- [AC-14] WHEN a stage is dispatched, the input contract (containing skill name, ticket body, and carry-forward context) SHALL appear in stdout and be visible in the ticket's history in the front end.
- [AC-15] WHEN an agent completes a stage, the output contract (containing status and structured data) SHALL appear in stdout and be visible in the ticket's history in the front end.
- [AC-21] The configured egress allowlist (LLM API endpoints, package registries, MCP endpoints) SHALL be visible in stdout on startup. An agent sandbox SHALL be able to reach allowed destinations — observable by successful tool calls appearing in the agent session output.
- [AC-22] IF an agent attempts network access to a destination not in the allowlist, THEN stdout SHALL log `blocked egress: <destination> from ticket <id>` with a timestamp and the agent's session output SHALL show the connection failure.
- [AC-23] Any attempt by an agent to run a git command SHALL fail — observable by `git` returning an error in the agent session output. The orchestrator, not the agent, performs all git operations.

### Architectural Constraints

**Module: `platform.agent_client`** — OpenCode HTTP client

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

**Module: `platform.agent_config`** — per-skill agent configuration

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

**Module: `platform.dispatch`** — full agent lifecycle

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

**Module: `workflows.sdd.skill_configs`** — declarative skill → config mapping

```python
SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True, "task": False, "webfetch": False},
        mcps={},
    ),
}
```

**Decisions made** (from gap analysis):

- Per-dispatch `opencode.json` generated by the orchestrator and written to workspace root before container creation. Contains provider definitions, permission rules, and MCP toggles.
- `dispatch()` is the single platform function for the full agent lifecycle: config write → container create → health check (`GET /api/health`) → credential inject (`PUT /auth/:id`) → session create (`POST /session`) → prompt (`POST /session/{id}/message`, blocks) → outcome read → container destroy. Always destroys container before raising on failure.
- Per-invocation model selection via `model: {providerID, modelID}` in the message body. Per-invocation tool enable/disable via `tools: {tool_name: bool}` in the message body.
- Skills are bind-mounted read-only from `.agents/skills/` into the sandbox. No file copying per dispatch. Skills retain `if git is available` git steps — git is unavailable in sandbox per egress policy.
- No named agent profiles — model and tools are set per invocation via `POST /session/{id}/message`.
- JSON contracts via prompt embed (outbound) and `outcome_path` file (inbound). Skills write structured JSON; orchestrator reads and validates.

**ADR-0005**: No long-lived credentials in agent sandbox — LLM API keys are never stored in environment variables, files, or any persistent location inside the sandbox container. The orchestrator injects credentials into opencode's memory via `PUT /auth/:id` after container startup and before the prompt. Credentials exist only in the opencode server process for the duration of the sandbox session.

**ADR-0001**: LangGraph as pipeline engine — free, MIT-licensed, self-hosted. Provides checkpointer, retry policy, timeout, interrupt/resume, and state streaming.

**Open Risks** (from gap analysis):

- **opencode /session API stability** — The `/session/*` and `PUT /auth/:id` endpoints are newer than the `/api/*` surface. Contract shape may change. Version-pin the opencode npm package in the sandbox image.
- **opencode message endpoint blocking** — Assumes `POST /session/{id}/message` blocks until the agent turn is complete (tool loop handled server-side). If it returns after a single response, a polling fallback via `GET /session/{id}` is needed.
- **auth.set provider recognition** — `PUT /auth/:id` requires the provider to be defined in `opencode.json` for opencode to accept the key. Provider ID in the URL must match the provider key in the config.
- **Outcome_path convention** — Skills are instructed to write to `outcome_path`. If a skill doesn't respect this (e.g., writes somewhere else), the orchestrator gets no output. Mitigated by prompt instructions and verified in pipeline tests.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.
- The target project must not be this repo (bp-agents).

## This Ticket's Acceptance Criteria

- [ ] `OpenCodeClient` creates session via `POST /session`, sends message via `POST /session/{id}/message`, gets status via `GET /session/{id}`
- [ ] `OpenCodeClient.auth_set()` injects credentials via `PUT /auth/{provider_id}` — never via env vars or files
- [ ] `OpenCodeClient.abort()` kills a running session via `POST /session/{id}/abort`
- [ ] `AgentConfig` dataclass with model, provider, permissions, tools, mcps fields
- [ ] `to_opencode_json()` generates valid `opencode.json` from `AgentConfig` + provider defs + MCP defs
- [ ] `dispatch()` executes full agent lifecycle: config write → container create → health check → credential inject → session create → message → outcome read → container destroy
- [ ] `dispatch()` always destroys container on failure
- [ ] Skills bind-mounted read-only — no `shutil.copytree` of skills per dispatch
- [ ] TDD node uses `dispatch()` with `SKILL_CONFIGS["tdd"]`
- [ ] Orchestrator commits agent changes to feature branch of target project after TDD success
- [ ] Input contract (skill, ticket body, context) logged to stdout
- [ ] Output contract (status, summary, test results) logged to stdout
- [ ] Agent-declared blocked (`status: BLOCKED`) transitions ticket to Blocked without commit

## Outcome

Implementer, reviewer, reduction auditor, and QA subagents all completed. All 13 acceptance criteria satisfied. Three commit rounds:
1. `7ab3040` — Initial implementation (agent_client, agent_config, dispatch, skill_configs, TDD node) with 153 tests
2. `128d7d6` — Review fixes: ADR-0005 credential security (strip API key from sandbox env, remove env lookup from PROVIDER_DEFINITIONS), added tools=None test, extended E2E test, shared WORKSPACE_MOUNT_PATH constant
3. `d685a1b` — Reduction fixes: deleted dead code (list_containers, OutcomeMissingError, GVisorSandbox), shared CREDENTIAL_KEYS constant, factory collapse in skill_configs (-105 lines), wired session_status polling and abort into dispatch
4. `da2650a` — QA fixes: abort before close in dispatch finally block (prevents container leak), TimeoutError added to TDD retry-able exceptions

Artefacts:
- `.scratch/orchestrator/outcomes/implement-outcome.json`
- `.scratch/orchestrator/outcomes/review-outcome.json`
- `.scratch/orchestrator/outcomes/reduction-outcome.json`
- `.scratch/orchestrator/outcomes/verify-outcome.json`