# 02 — Contract-Broker MCP Server

Status: done

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- ADRs: 0001-0005
- Glossary: `CONTEXT.md`

## What Done Means

**Feature-level** (verbatim from the requirements doc):

> I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

**This ticket:** After this ticket, `TddOutput`, `ReviewOutput`, and `RevisionOutput` are Pydantic `BaseModel` classes in `workflows/sdd/contracts/`. The `ContractBroker` class in `platform/mcp/contract_broker.py` validates submissions against these models, manages per-dispatch bindings with retry caps and lock-on-success, and exposes `submit_contract` as an MCP tool via FastMCP. Verifiable in isolation via unit tests and a FastMCP integration test.

## What to Build

### Pydantic migration

Convert `TddOutput`, `ReviewOutput`, and `RevisionOutput` from `TypedDict` to `pydantic.BaseModel` in `workflows/sdd/contracts/__init__.py`. Same fields, same types — only the base class changes. Update all imports and usages in `workflows/sdd/state.py`, `workflows/sdd/tdd.py`, and any other modules that construct or read these types. The models are the single source of truth: the broker validates against them, the graph parses them.

### ContractBroker class

Implement `ContractBroker` in `platform/mcp/contract_broker.py` using the exact interface from the gap analysis:

- **Schema registry**: `register(workflow, stage, model: type[BaseModel])` — workflows call this at startup. Idempotent. Raises on duplicate registration for different model types.
- **Binding lifecycle**: `create_binding(workflow, stage, run_id, max_attempts=3, ttl_seconds=3600.0) -> str` — returns opaque token via `secrets.token_urlsafe()`. Raises `ValueError` if (workflow, stage) not registered.
- **Submit**: `submit(token, payload) -> dict` — validates payload against registered Pydantic model. Returns `SubmitResult` as dict. On first acceptance: sets `asyncio.Event` (lock-on-success). On rejection (validation error): increments attempt counter, returns structured errors. On max attempts exceeded: returns terminal error. On already accepted: returns terminal "already submitted" error. On unknown/expired token: returns terminal error.
- **Await acceptance**: `await_acceptance(token) -> AcceptedContract` — blocks on `asyncio.Event` until a valid contract is submitted. Cancellable. Raises `ValueError` if token unknown.
- **Invalidate**: `invalidate(token)` — removes binding and its event. Idempotent.

### FastMCP integration

Wrap the broker in a FastMCP server. The `submit_contract` tool accepts `token: str` and `payload: dict` parameters, delegates to `broker.submit()`, and returns the result dict. The server starts on a configurable port.

### Testing

Unit-test the `ContractBroker` in isolation: schema registration, binding creation, valid/invalid submission, retry counting, lock-on-success, invalidation, expiry. One integration test that starts FastMCP on a random port, calls `submit_contract` via HTTP, and verifies the response.

## Requirements

### User Stories

From `docs/requirements/mcp-contract-broker-observability.md`:

> - As a **developer**, I want contract schemas defined once as Pydantic models that both the MCP server and LangGraph nodes use, so there is no schema drift between what the agent must produce and what the graph expects.
> - As a **developer**, I want the contract-broker to be platform infrastructure reusable by all workflows, so I don't rebuild contract validation for each new agent.

### Domain Context

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Contract-Broker MCP Server
>
> A long-lived MCP server hosted in the orchestrator process. Exposes one or more tools that agents call to submit their stage output. The broker validates submissions against workflow-defined Pydantic schemas and either accepts or returns structured validation errors.
>
> **Per-dispatch binding**: Each sandbox dispatch is bound to a specific workflow, stage, and run. The agent cannot choose or change the target schema — the binding is established by the orchestrator at dispatch time and expires when the sandbox session ends.
>
> **Validation retry**: The agent may submit an invalid contract and receive validation errors. The broker allows a configurable number of failed attempts per run (default: 3). On the final attempt, the broker returns a terminal error instructing the agent to stop. The agent's own max-turns and timeout are backstop limits underneath the broker's retry cap.
>
> **Lock-on-success**: Once the broker accepts a valid submission for a run, further submissions for that run are rejected. This prevents a confused agent from overwriting a good contract with a worse one later in the same session.

### Behavioral Scenarios

None (end-to-end scenarios covered by issue 05).

### Acceptance Criteria

From `docs/requirements/mcp-contract-broker-observability.md`:

> - [AC-10] The contract-broker MCP server SHALL reside under `src/bp_agents/platform/mcp/`. Workflow contract models SHALL be Pydantic `BaseModel` classes under the workflow's `contracts.py`. The `src/platform/` and `src/workflows/` stub directories SHALL NOT exist.
> - [AC-11] The same Pydantic model class SHALL be used by the contract-broker for MCP tool input validation AND by the LangGraph node for parsing the returned contract. Discrepancy between the MCP schema and the graph's expected schema SHALL NOT be possible without a code change visible in the same file.

### Architectural Constraints

From `docs/architecture/gap-analysis-contract-broker.md`:

**`platform/mcp/contract_broker.py`**:

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

**`workflows/sdd/contracts/__init__.py`** (Pydantic models):

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

Decisions:

> - **Schema registry pattern** — workflows register Pydantic models with the broker at startup. Platform never imports workflow types.
> - **In-process contract-broker** — runs in orchestrator process via FastMCP. Shares memory with dispatch() for `asyncio.Event`-based notification. Extracted to separate service if multiple stateful MCPs emerge.
> - **Per-dispatch binding tokens** — opaque random strings (secrets.token_urlsafe). Scoped to (workflow, stage, run_id). Ephemeral — invalidated on acceptance or session end.
> - **Structured SubmitResult** — all broker responses are `accepted: bool` with structured errors. No exceptions cross the MCP boundary. Terminal flag for max-attempts and lock-on-success.
> - **TypedDict → Pydantic BaseModel** — same file, same fields. `model_validate()` for broker, `model_dump()` for graph state.
> - **Token in prompt** — binding token embedded in skill prompt prose, not opencode.json MCP config.

### Testing Decisions

None specific — unit tests for broker logic, one FastMCP integration test.

### Non-Functional Requirements

From `docs/requirements/mcp-contract-broker-observability.md`:

> - Contract-broker validation must not introduce perceptible latency beyond normal MCP tool call overhead (sub-second for Pydantic validation).
> - Per-dispatch bindings (tokens) must not be reusable across sandbox sessions and must not grant access to contracts from other runs.
> - The contract-broker must not persist contracts to disk — contracts live in memory for the duration of the dispatch call only.

## This Ticket's Acceptance Criteria

- [ ] `TddOutput`, `ReviewOutput`, `RevisionOutput` are `pydantic.BaseModel` subclasses in `workflows/sdd/contracts/__init__.py`
- [ ] All existing imports and usages of these types compile and pass existing tests
- [ ] `ContractBroker.register()` accepts a Pydantic model and makes it available for validation
- [ ] `ContractBroker.create_binding()` returns an opaque token scoped to (workflow, stage, run_id)
- [ ] `ContractBroker.submit()` validates payload against the registered Pydantic model
- [ ] `ContractBroker.submit()` returns `{"accepted": true, ...}` with the validated contract on valid payload
- [ ] `ContractBroker.submit()` returns `{"accepted": false, "errors": [...], "attempts_remaining": N, "terminal": false}` on invalid payload
- [ ] `ContractBroker.submit()` returns `{"accepted": false, "terminal": true}` after max_attempts exhausted
- [ ] `ContractBroker.submit()` returns terminal error ("already submitted") when called again after acceptance
- [ ] `ContractBroker.submit()` returns terminal error for unknown/expired token
- [ ] `ContractBroker.await_acceptance()` blocks until `submit()` accepts a contract, then returns `AcceptedContract`
- [ ] `ContractBroker.invalidate()` removes binding; subsequent `await_acceptance()` raises
- [ ] FastMCP server exposes `submit_contract(token, payload)` tool via HTTP
- [ ] FastMCP integration test: start server on random port, POST tool call, verify result

## Blocked by

- 01-code-org-refactor.md

## Outcome

Pydantic migration (TddOutput/ReviewOutput/RevisionOutput → BaseModel) + ContractBroker class with schema registry, binding lifecycle, Pydantic validation, retry caps, lock-on-success, expiry, invalidation, and FastMCP server wired into orchestrator main.py. All 22 broker-specific tests pass (8 ACs covered), plus 163 pre-existing tests passing.

- Implement: `.scratch/mcp-contract-broker/outcomes/implement-outcome.json`
- Review: `.scratch/mcp-contract-broker/outcomes/review-outcome.json`
- Reduction: `.scratch/mcp-contract-broker/outcomes/reduction-outcome.json`
- Verify: `.scratch/mcp-contract-broker/outcomes/verify-outcome.json`

## Comments