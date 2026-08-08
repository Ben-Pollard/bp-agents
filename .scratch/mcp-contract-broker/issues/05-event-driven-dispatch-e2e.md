# 05 — Event-Driven Dispatch & End-to-End

Status: ready-for-agent

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- ADRs: 0001-0005
- Glossary: `CONTEXT.md`

## What Done Means

**Feature-level** (verbatim from the requirements doc):

> I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

**This ticket:** After this ticket, the full feature works end-to-end. A user submits a ticket, the TDD agent delivers its contract via `submit_contract` MCP tool, the ticket advances to `awaiting_review`, and all behavioral scenarios pass: happy path, invalid contract with retry, max retries exhausted, lock-on-success, and dispatch timeout.

## What to Build

### dispatch() rewrite

Rewrite `dispatch()` in `platform/dispatch.py` to be event-driven. The new signature includes `broker: ContractBroker` and `binding_token: str`. Remove `outcome_path` parameter and `OUTCOME_FILENAME` constant (they remain only for non-contract workspace file access).

Flow:
1. Write `opencode.json` to workspace root — includes MCP contract-broker URL from `MCP_DEFS`, OTEL experimental flag, provider definitions, permissions, MCP toggles
2. Write sandbox env with `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at the orchestrator's OTEL receiver port
3. Create container, health check
4. `PUT /auth/{provider}` inject credentials
5. `POST /session` create session
6. `POST /session/{id}/message` send prompt (includes binding token in prose) — non-blocking send
7. `await broker.await_acceptance(binding_token)` — blocks until contract accepted
8. On acceptance: abort session, destroy container, return `AcceptedContract`
9. On cancellation (LangGraph timeout): destroy container, invalidate binding, let exception propagate

No internal timeout — LangGraph's node `timeout` parameter handles it. No file read for contract delivery. Container always destroyed in `finally` block (or by sandbox cleanup on exception).

### TddNode simplification

Remove the `for attempt in range(max_retries)` retry loop from `TddNode.__call__()`. Remove `validate_tdd_output()` and `FAIL` status re-dispatch logic. The method becomes:

1. Ensure feature branch
2. Create binding token via `self._broker.create_binding("sdd", "tdd", run_id)`
3. Build prompt with token embedded
4. `accepted = await dispatch(...)` — single call, no loop, no manual retry
5. On return: `_clean_artifacts()`, git commit, advance state to `awaiting_review`

TddNode constructor gains `broker: ContractBroker` parameter. The `_handle_non_complete` method and FAIL/BLOCKED retry logic are removed — the agent communicates status through the contract payload, not through the node's retry logic.

### LangGraph node configuration

Configure the TDD node with LangGraph's composable fault tolerance:

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
    error_handler=_handle_implement_error,
)
```

`_handle_implement_error` runs after all node retries are exhausted. It updates the tracker to Blocked with an appropriate reason and logs the failure.

### SKILL_CONFIGS update

All SDD stages that dispatch agents (`tdd`, `code_review`, `revision`, `minimizing_code`, `behavioral_verify`, `deterministic_gate`) toggle `"contract-broker": True` in their `mcps` dict.

### MCP_DEFS update

Add the contract-broker MCP server definition to `MCP_DEFS` in `dispatch.py`:

```python
MCP_DEFS = {
    "contract-broker": {
        "type": "http",
        "url": "http://orchestrator:{broker_port}/mcp",
    },
}
```

### Orchestrator wiring (main.py)

At startup, `main.py` creates the `ContractBroker`, registers schemas from each workflow (`broker.register("sdd", "tdd", TddOutput)` etc.), starts the FastMCP server, starts the `OtelReceiver`, and passes the broker to graph construction.

### End-to-end verification

All behavioral scenarios from the requirements doc must pass:
- Happy path agent submit → broker accept → ticket advance
- Invalid contract → broker rejects with errors → agent retries → acceptance
- Max retries exhausted → broker returns terminal → ticket blocked
- Lock-on-success double-submit → second submission rejected
- Dispatch timeout → LangGraph retries → ticket blocked after retries exhausted

## Requirements

### User Stories

From `docs/requirements/mcp-contract-broker-observability.md`:

> - As a **developer**, I want the agent to receive immediate feedback when its contract output doesn't match the required schema, so it can correct mistakes during the session rather than failing silently.
> - As a **QA agent**, I want to see LLM messages and tool calls from a failed agent session, so I can determine why the agent failed without re-running the session or reading source code.
> - As a **developer**, I want contract schemas defined once as Pydantic models that both the MCP server and LangGraph nodes use, so there is no schema drift between what the agent must produce and what the graph expects.

### Domain Context

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Agent-Loop Retry vs Node-Level Retry
>
> Two distinct retry layers:
>
> - **Agent-loop retry** (inside the sandbox): The contract-broker validates and returns errors to the agent. The agent corrects and resubmits — full session context is preserved. Handles invalid contracts.
> - **Node-level retry** (LangGraph): Handles transport failures (sandbox unreachable, timeout) via LangGraph's `retry_policy`, `timeout`, and `error_handler` on `add_node()`. The error handler updates the tracker to reflect blocked/failed status after retries are exhausted.
>
> The TDD node no longer has its own retry loop. Contract status values (DONE, BLOCKED, FAIL) are routing signals for the graph, not retry triggers.
>
> ### Dispatch Flow
>
> The `dispatch()` function changes from file-read to event-driven:
>
> 1. Write opencode.json (includes contract-broker MCP URL and per-dispatch binding)
> 2. Create sandbox, health check, inject credentials, create session, send prompt
> 3. Await either a valid contract submission (broker event) or a timeout
> 4. On contract event: abort session, return validated contract
> 5. On timeout: destroy sandbox, raise failure (handled by LangGraph retry)
>
> The `outcome_path` environment variable and `OUTCOME_FILENAME` constant become obsolete for contract delivery.

### Behavioral Scenarios

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Scenario: Happy path — agent submits valid contract via MCP
>
> 1. Orchestrator poll finds a ready ticket, routes it to the SDD pipeline graph.
> 2. The TDD node calls `dispatch()`, which creates a sandbox and sends the TDD prompt (including the contract-broker MCP URL and per-dispatch binding).
> 3. The agent writes code and tests, then calls `submit_contract` with a valid `TddOutput` payload.
> 4. The contract-broker validates the payload against the `TddOutput` Pydantic model, accepts it, and signals the dispatcher.
> 5. `dispatch()` logs the accepted contract to stdout, aborts the agent session, and returns the validated contract to the TDD node.
> 6. The TDD node commits the agent's changes to the feature branch, logs the state transition, and the ticket advances to Awaiting review.
> 7. The `outcome.json` file is never written to the workspace.
>
> ### Scenario: Invalid contract, agent retries and succeeds
>
> 1. Agent calls `submit_contract` with a payload missing the `test_results` field.
> 2. Contract-broker rejects with validation errors: "Missing required field: test_results."
> 3. Agent sees the error, corrects the payload, calls `submit_contract` again.
> 4. This time the broker accepts the payload.
> 5. Orchestrator stdout logs show: attempt 1 (rejected), attempt 2 (accepted). Ticket advances normally.
>
> ### Scenario: Max validation retries exhausted
>
> 1. Agent calls `submit_contract` with an invalid payload.
> 2. Broker rejects with validation errors. Agent resubmits — still invalid.
> 3. Agent resubmits a third time — still invalid. This is the final allowed attempt.
> 4. Broker returns a terminal error: "Max attempts exceeded, stop and end session."
> 5. `dispatch()` logs the terminal error to stdout. The agent session is aborted.
> 6. The TDD node's error handler updates the tracker: ticket transitions to Blocked with reason "agent: contract validation failed after 3 attempts."
>
> ### Scenario: Lock-on-success prevents overwrite
>
> 1. Agent calls `submit_contract` with a valid payload. Broker accepts.
> 2. Agent (confused) calls `submit_contract` again during the same session.
> 3. Broker rejects: "Run already has an accepted submission."
> 4. `dispatch()` returns only the first accepted contract. The second rejection is logged at info level.
>
> ### Scenario: Dispatch timeout with no contract
>
> 1. Orchestrator dispatches a TDD agent with a 30-minute timeout.
> 2. Agent runs for 30 minutes without submitting a valid contract.
> 3. `dispatch()` times out, destroys the sandbox, and raises a timeout exception.
> 4. LangGraph's `retry_policy` retries the node. If retries are exhausted, LangGraph's `error_handler` runs: updates tracker, ticket transitions to Blocked with "auto: stage timeout."

### Acceptance Criteria

From `docs/requirements/mcp-contract-broker-observability.md`:

> - [AC-01] (Scenario: Happy path) WHEN an agent calls `submit_contract` with a valid payload, orchestrator stdout SHALL log the accepted contract with ticket ID, stage, and run ID, and the ticket SHALL transition from the dispatched stage to the next stage in the pipeline.
> - [AC-02] (Scenario: Happy path) WHEN a valid contract is accepted, the `outcome.json` file SHALL NOT appear in the workspace.
> - [AC-03] (Scenario: Invalid contract, agent retries and succeeds) WHEN the agent submits an invalid contract, orchestrator stdout SHALL log the rejection with validation errors. IF the agent resubmits a valid payload on a subsequent attempt, stdout SHALL log the accepted contract and the ticket SHALL advance.
> - [AC-04] (Scenario: Max validation retries exhausted) WHEN the agent exhausts the allowed validation attempts, orchestrator stdout SHALL log a terminal error ("max attempts exceeded"), the agent session SHALL end, and the ticket SHALL appear in the Blocked state with a reason indicating contract validation failure.
> - [AC-05] (Scenario: Lock-on-success prevents overwrite) WHEN a valid contract has already been accepted for a run, any subsequent `submit_contract` call SHALL be rejected, stdout SHALL log the rejection ("already submitted"), and ONLY the first accepted contract SHALL be delivered to the LangGraph node.
> - [AC-09] (Scenario: Dispatch timeout with no contract) WHEN a dispatched agent session reaches its timeout without a valid contract submission, orchestrator stdout SHALL log the timeout, the sandbox SHALL be destroyed, and the ticket SHALL either retry (if retries remain) or transition to Blocked (if retries exhausted) with "stage timeout" in the reason.

Also verified end-to-end (built in prior slices, verified here):

> - [AC-06] WHERE log level is set to `debug`, orchestrator stdout SHALL include agent LLM request and response messages, tool calls, and session errors for every turn of the agent session.
> - [AC-07] WHERE log level is set to `info`, orchestrator stdout SHALL include session status changes and errors but SHALL NOT include full LLM message content.
> - [AC-11] The same Pydantic model class SHALL be used by the contract-broker for MCP tool input validation AND by the LangGraph node for parsing the returned contract.

### Architectural Constraints

From `docs/architecture/gap-analysis-contract-broker.md`:

**Updated `platform/dispatch.py`**:

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

**Updated `workflows/sdd/tdd.py`**:

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

**Updated `workflows/sdd/graph.py`**:

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

**`opencode.json` additions**:

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
  }
}
```

**`SKILL_CONFIGS` update**:

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

**Prompt format**:

```
submit_contract token: {binding_token}
outcome_path: {outcome_path}  # fallback for local opencode sessions
```

**Sandbox environment**:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://orchestrator:{otel_port}
```

Decisions:

> - **Event-driven dispatch** — dispatch() awaits `broker.await_acceptance(token)`. No internal timeout. LangGraph `timeout` + `retry_policy` + `error_handler` composably handle timeouts/retries/cleanup.
> - **Token in prompt** — binding token embedded in skill prompt prose, not opencode.json MCP config.

### Testing Decisions

None specified — implementation agent determines appropriate test levels.

### Non-Functional Requirements

None additional (all NFRs covered by prior slices).

## This Ticket's Acceptance Criteria

- [ ] `dispatch()` signature changed: `outcome_path` removed, `broker` and `binding_token` added
- [ ] `dispatch()` writes opencode.json with MCP contract-broker URL and OTEL experimental flag
- [ ] `dispatch()` writes `OTEL_EXPORTER_OTLP_ENDPOINT` into sandbox env
- [ ] `dispatch()` blocks on `broker.await_acceptance(binding_token)` after sending prompt
- [ ] `dispatch()` aborts session and destroys container on acceptance
- [ ] `dispatch()` destroys container and invalidates binding on cancellation/timeout
- [ ] `OUTCOME_FILENAME` constant removed from contract delivery path
- [ ] `TddNode.__call__()` has no retry loop — single `dispatch()` call
- [ ] `TddNode.__call__()` commits agent changes and advances state to `awaiting_review` on success
- [ ] `TddNode` constructor takes `broker: ContractBroker`
- [ ] `validate_tdd_output()` and `_handle_non_complete` removed from TddNode
- [ ] TDD node configured with LangGraph `timeout=1800.0`, `retry_policy`, and `error_handler`
- [ ] `_handle_implement_error` updates tracker to Blocked with appropriate reason
- [ ] `SKILL_CONFIGS` toggles `contract-broker: True` for all dispatch stages
- [ ] `MCP_DEFS` includes contract-broker definition
- [ ] Happy path e2e: agent submits valid contract → broker accepts → ticket advances → no outcome.json in workspace (AC-01, AC-02)
- [ ] Invalid contract e2e: agent submits invalid → broker rejects with errors → agent retries → acceptance (AC-03)
- [ ] Max retries e2e: agent exhausts attempts → broker returns terminal → ticket blocked (AC-04)
- [ ] Lock-on-success e2e: accepted contract → second submission rejected (AC-05)
- [ ] Timeout e2e: agent doesn't submit → LangGraph timeout → retry → blocked after exhaustion (AC-09)

## Blocked by

- 02-contract-broker-mcp-server.md
- 03-otel-session-observability.md
- 04-skill-dual-context-update.md