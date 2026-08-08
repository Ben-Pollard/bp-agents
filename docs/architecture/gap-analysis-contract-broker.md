# Architecture Gap Analysis — Contract Broker & Observability

> Last updated: 2026-08-08
> Triggered by: `docs/requirements/mcp-contract-broker-observability.md`

## Current State

Issue #04 complete: `OpenCodeClient` (httpx wrapper), `TddNode` with env-var credential forwarding, Redmine tracker via `platform.tracker`, gVisor sandbox, LangGraph pipeline engine with SQLite checkpointer. ADRs 0001-0005 in place.

Contract delivery: skills write `outcome.json` to workspace. dispatch() reads the file after agent session ends. No real-time validation feedback loop. TddNode has its own retry loop wrapping dispatch().

Observability: Langfuse for traces (ADR-0004). No per-turn LLM message visibility without Langfuse. Sandbox destroyed on failure takes all session context with it.

Platform/workflow dependency direction: platform never imports workflow types. Tracker uses an ABC port in platform with workflow adapters.

## Required Changes

- **Contract-broker MCP server** — in-process FastMCP server running in the orchestrator. Exposes `submit_contract` tool. Validates submissions against workflow-registered Pydantic schemas. Manages per-dispatch bindings with retry caps and lock-on-success.
- **Schema registry pattern** — workflows register their Pydantic contract models with the broker at startup. Platform code never imports workflow types. Same pattern as `Tracker` ABC → `RedmineTracker` adapter.
- **Event-driven dispatch** — dispatch() replaces file-read with `broker.await_acceptance(token)`. No internal timeout — LangGraph handles timeout/retry/error_handler. No outcome_path read. OUTCOME_FILENAME constant removed from contract delivery.
- **Per-dispatch binding tokens** — opaque random strings. Scoped to (workflow, stage, run_id). Ephemeral — invalidated on acceptance or session end. Token injected into the skill prompt text.
- **OTEL observability pipeline** — opencode native OTEL support (`experimental.openTelemetry: true` + `OTEL_EXPORTER_OTLP_ENDPOINT` env var) → OTLP/HTTP → orchestrator's OtelReceiver → stdout. Best-effort. Log level filters: info=status+errors, debug=full LLM traces.
- **TypedDict → Pydantic** — `TddOutput`, `ReviewOutput`, `RevisionOutput` become `pydantic.BaseModel`. Same file (`workflows/sdd/contracts/__init__.py`). Used by both broker (validation) and graph (parsing).
- **TddNode retry loop removal** — TddNode becomes a single dispatch() call. Agent-loop retry (via broker feedback) handles invalid contracts. LangGraph retry_policy handles transport failures. TddNode's `max_retries` loop, `validate_tdd_output`, and FAIL status re-dispatch are removed.
- **Skill dual-context compatibility** — skills check for `submit_contract` tool availability. If present, use it; otherwise write to `outcome_path`.
- **New platform modules** — `platform/mcp/contract_broker.py`, `platform/observability/otel_receiver.py`. No `src/platform/` stub — everything under `src/bp_agents/platform/`.

## Module Interfaces

### `platform/mcp/contract_broker.py`

```python
from dataclasses import dataclass, field
import asyncio
import secrets
import time

from pydantic import BaseModel, ValidationError


@dataclass
class SubmitResult:
    accepted: bool
    contract: dict | None = None
    errors: list[dict] | None = None        # [{"field": "...", "message": "..."}]
    attempts_remaining: int | None = None
    terminal: bool = False


@dataclass
class AcceptedContract:
    workflow: str
    stage: str
    run_id: str
    contract: dict


class ContractBroker:
    """In-process MCP server managing contract submission lifecycle.

    Workflows register Pydantic schemas at startup. dispatch() creates
    per-run bindings. The agent calls submit_contract via MCP; the broker
    validates and fires an asyncio.Event that dispatch() awaits.
    """

    def __init__(self) -> None: ...

    # --- Schema registry (called at startup by workflows) ---
    def register(self, workflow: str, stage: str, model: type[BaseModel]) -> None:
        """Register a Pydantic model for (workflow, stage). Idempotent."""

    # --- Binding lifecycle (called by dispatch()) ---
    def create_binding(
        self,
        workflow: str,
        stage: str,
        run_id: str,
        max_attempts: int = 3,
        ttl_seconds: float = 3600.0,
    ) -> str:
        """Create a per-dispatch binding. Returns opaque token.
        Raises ValueError if (workflow, stage) not registered."""

    async def await_acceptance(self, token: str) -> AcceptedContract:
        """Block until a valid contract is submitted for this token.
        Raises asyncio.CancelledError on shutdown.
        Raises ValueError if token unknown/expired/invalidated."""

    def invalidate(self, token: str) -> None:
        """Remove binding. Safe to call multiple times."""

    # --- MCP tool handler (called by FastMCP) ---
    def submit(self, token: str, payload: dict) -> dict:
        """Validate payload against registered schema. Returns SubmitResult as dict.
        Sets the asyncio.Event on first acceptance (lock-on-success).
        Returns terminal error on max attempts exceeded, already accepted,
        or unknown/expired token."""
```

### `platform/observability/otel_receiver.py`

```python
class OtelReceiver:
    """OTLP/HTTP receiver that logs spans to stdout.

    Best-effort: failures are logged and swallowed, never propagate to caller.
    Log level filtering: info=session_status + session_error events only;
    debug=all spans including llm_message and tool_call.
    """

    def __init__(self, log_level: str = "info") -> None:
        """log_level: 'info' or 'debug'."""

    async def start(self, port: int = 4318) -> None:
        """Start OTLP/HTTP server on 0.0.0.0:{port}.
        Accepts POST /v1/traces with OTLP protobuf payload."""

    async def stop(self) -> None:
        """Graceful shutdown."""
```

### Updated `platform/dispatch.py`

```python
async def dispatch(
    sandbox: Sandbox,
    sandbox_config: SandboxConfig,
    config: AgentConfig,
    prompt: str,
    workspace: str,
    api_key: str,
    broker: ContractBroker,
    binding_token: str,
    otel_port: int = 4318,
) -> AcceptedContract:
    """Full agent lifecycle, event-driven contract delivery.

    1. Write opencode.json (MCP broker URL + OTEL endpoint + config)
    2. Create container, health check
    3. PUT /auth/{provider} inject creds
    4. POST /session create session
    5. POST /session/{id}/message send prompt (non-blocking)
    6. await broker.await_acceptance(binding_token)
    7. On acceptance: abort session, destroy container, return contract
    8. On cancellation/timeout: destroy container, invalidate binding

    No outcome_path parameter. No OUTCOME_FILENAME read.
    No internal timeout — LangGraph node config provides timeout/retry.
    Container always destroyed in finally block.
    """
```

### Updated `workflows/sdd/contracts/__init__.py`

```python
from pydantic import BaseModel
from typing import Literal

class TddOutput(BaseModel):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL"]
    summary: str
    test_results: dict     # {"passed": N, "failed": N, "skipped": N}
    concerns: list[str]

class ReviewOutput(BaseModel):
    spec_compliance: bool
    code_quality: dict[str, bool]
    test_quality: dict[str, bool]
    operational: bool
    violations: list[dict]
    review_notes: list[str]
    action: Literal["approved", "changes_requested"]

class RevisionOutput(BaseModel):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    violations_addressed: list[dict]
    violations_pushed_back: list[dict]
    violations_unclear: list[dict]
    test_results: dict
    concerns: list[str]
```

### Updated `workflows/sdd/tdd.py`

```python
class TddNode:
    def __init__(
        self,
        sandbox: Sandbox,
        sandbox_config: SandboxConfig,
        target_repo_path: str,
        skills_path: str,
        broker: ContractBroker,
        tracker: Tracker | None = None,
        client: OpenCodeClient | None = None,
    ) -> None: ...

    async def __call__(self, state: TicketPipelineState) -> dict:
        """Single dispatch call. No retry loop. No validate_tdd_output.
        LangGraph handles retry/timeout. Broker handles validation."""
        # 1. Ensure feature branch
        # 2. Create binding token via broker.create_binding()
        # 3. Build prompt with token embedded
        # 4. await dispatch(...) — single call, no loop
        # 5. On return: git commit, advance state
```

### Updated `workflows/sdd/graph.py`

TDD node configured with LangGraph retry/timeout/error_handler:

```python
builder.add_node(
    "implement",
    implement_node,
    retry=RetryPolicy(
        max_attempts=3,
        initial_interval=10.0,
        backoff_factor=2.0,
        retry_on=(httpx.ConnectError, httpx.TimeoutException, TimeoutError),
    ),
    timeout=1800.0,  # 30 min per attempt
    error_handler=_handle_implement_error,  # updates tracker after retries exhausted
)
```

### `opencode.json` additions

```jsonc
{
  "experimental": {
    "openTelemetry": true
  },
  "mcp": {
    "contract-broker": {
      "type": "http",
      "url": "http://orchestrator:{broker_port}/mcp",
      "enabled": true
    }
  },
  // existing provider, permission, skills, etc.
}
```

### `SKILL_CONFIGS` update

```python
SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": AgentConfig(
        ...,
        mcps={"contract-broker": True},
    ),
    "code_review": AgentConfig(
        ...,
        mcps={"contract-broker": True},
    ),
    # ... other stages
}
```

### Prompt format (token injection)

The skill prompt includes the binding token as prose:

```
submit_contract token: {binding_token}
outcome_path: {outcome_path}  # fallback for local opencode sessions
```

### Sandbox environment additions

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://orchestrator:{otel_port}
```

## Decisions Made

- **Schema registry pattern** — workflows register Pydantic models with the broker at startup. Platform never imports workflow types.
- **In-process contract-broker** — runs in orchestrator process via FastMCP. Shares memory with dispatch() for `asyncio.Event`-based notification. Extracted to separate service if multiple stateful MCPs emerge.
- **Per-dispatch binding tokens** — opaque random strings (secrets.token_urlsafe). Scoped to (workflow, stage, run_id). Ephemeral — invalidated on acceptance or session end.
- **Event-driven dispatch** — dispatch() awaits `broker.await_acceptance(token)`. No internal timeout. LangGraph `timeout` + `retry_policy` + `error_handler` composably handle timeouts/retries/cleanup.
- **Structured SubmitResult** — all broker responses are `accepted: bool` with structured errors. No exceptions cross the MCP boundary. Terminal flag for max-attempts and lock-on-success.
- **TypedDict → Pydantic BaseModel** — same file, same fields. `model_validate()` for broker, `model_dump()` for graph state.
- **OTEL via opencode native** — `experimental.openTelemetry: true` + `OTEL_EXPORTER_OTLP_ENDPOINT` env var. Preferred path. Fallback: custom opencode OTEL plugin or existing `opencode-plugin-otel`.
- **Token in prompt** — binding token embedded in skill prompt prose, not opencode.json MCP config.
- **OtelReceiver in-process** — runs on dedicated port in orchestrator. Best-effort, never fails agent session.
- **No new ADRs** — decisions extend existing patterns (Tracker port → schema registry; ephemeral sandbox env → OTEL env vars).

## Decisions Deferred

- **Contract-broker extraction to separate service** — revisit when a second stateful MCP server needs the same notification pattern. In-process is simpler for V1.
- **OTEL span attribute contract** — exact span names and attributes from opencode's AI SDK will be discovered during implementation. Log level filtering rules may need adjustment.

## Affected Dimensions

| Dimension | Impact |
|---|---|
| Module decomposition | New: `platform/mcp/contract_broker.py`, `platform/observability/otel_receiver.py`. Updated: `dispatch.py`, `tdd.py`, `contracts/__init__.py` |
| Interface design | Broker: register, create_binding, submit, await_acceptance, invalidate. Receiver: start, stop. dispatch() signature changes (no outcome_path, +broker, +binding_token) |
| Seam placement | Contract delivery seam moves from file I/O to MCP tool call. Validation moves from TddNode post-hoc to broker in-session |
| Dependency direction | Preserved via schema registry — platform never imports workflow types |
| Domain boundaries | Agent-in-sandbox boundary gains MCP channel (contract-broker) and OTLP channel (observability) |
| Data models | TddOutput, ReviewOutput, RevisionOutput: TypedDict → Pydantic BaseModel |
| Data flow | File-read → event-driven. dispatch() awaits broker event instead of reading outcome_path |
| State ownership | Broker bindings in memory, per-dispatch lifecycle. Contracts not persisted to disk |
| Protocol choices | MCP (JSON-RPC/HTTP via FastMCP) added. OTLP/HTTP added |
| Message/event architecture | Broker uses asyncio.Event for dispatch notification. OTEL spans stream from sandbox to orchestrator |
| Reliability | Two retry layers: agent-loop (broker validation feedback) + LangGraph (transport). OTEL best-effort |
| Consistency | Lock-on-success provides write-once semantics per run |
| Security | Per-dispatch binding tokens — opaque, ephemeral, scoped. MCP broker is new attack surface in orchestrator |
| Error handling | Structured SubmitResult for all outcomes. No exceptions cross MCP boundary. Terminal errors for max attempts, lock-on-success, expired/invalid binding |
| Observability | New OTEL pipeline: opencode AI SDK spans → OTLP → orchestrator → stdout. Log level filtering via BP_LOG_LEVEL |
| Configuration | opencode.json additions: experimental.openTelemetry, MCP contract-broker URL. Token in prompt. OTEL_ENDPOINT env var in sandbox |
| Build | Sandbox image bakes OTEL SDK packages. FastMCP Python dependency added to orchestrator |
| Deployment | Contract-broker and OTEL receiver are in-process in orchestrator. No new containers |
| Repository structure | New `platform/mcp/` and `platform/observability/` directories under `src/bp_agents/platform/` |

## Open Risks

- **OTEL native support uncertainty** — opencode's `experimental.openTelemetry` + OTLP env vars path is documented by collaborators but the PR to add full OTEL support is still open. May need to fall back to a community plugin (`opencode-plugin-otel`) or write a custom one. Discovery needed during implementation.
- **FastMCP maturity** — FastMCP is the recommended library per requirements grilling. If it has gaps or instability, MCP protocol can be implemented with the lower-level `mcp` Python SDK.
- **Token in prompt visibility** — the binding token is visible to the agent. While tokens are ephemeral and scoped, a compromised agent could leak the token. Acceptable risk for V1 — token scope is limited to one dispatch.
- **OTEL SDK in sandbox image** — `@opentelemetry/sdk-node` and dependencies must be available in opencode's bun environment inside the sandbox. May require baking into the sandbox image or adding to opencode's global packages.json.
- **Span attribute discovery** — span names and attributes from Vercel AI SDK (`ai.streamText`, `ai.toolCall`) may change between opencode versions. Log level filtering rules are coupled to these names.