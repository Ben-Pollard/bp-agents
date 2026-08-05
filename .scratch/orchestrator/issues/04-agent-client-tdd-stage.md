Status: ready-for-human

# 04 — Agent client + TDD stage (first real dispatch)

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0002
- Glossary: `CONTEXT.md`

## What to Build

OpenCode HTTP client (`platform.agent_client`) wrapping `httpx` for opencode's HTTP API: create session, prompt, stream events, check session status. Then the TDD pipeline node — the first real agent dispatch. TDD node: creates sandbox, dispatches agent with ticket content, reads `outcome_path` file for structured JSON output, commits agent's work to feature branch. Both input and output contracts logged to stdout and queryable. Agent-declared block (`status: blocked` in output) transitions ticket to Blocked.

After this slice, a ticket flows Ready → Implementing → Awaiting Review with real agent work committed to a feature branch of the target project and the correct ticket status visible in redmine.

## Requirements

### User Stories

- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.

### Domain Context

**Contracts** (from reqs doc):

Each skill stage has a defined input contract and output contract. The input contract contains at minimum: skill name, ticket body, and carry-forward context from prior stages. The output contract contains at minimum: outcome status and structured data for the next stage. Contracts are observable — dispatched and returned in the trace.

Outcome statuses:
- `complete` — stage succeeded, advance to next stage.
- `blocked` — agent cannot proceed; transition to Blocked with reason.
- `fail` — transient error; retry per stage config.

**Pipeline** (from reqs doc) — TDD stage:

1. **TDD** — Orchestrator creates a feature branch from main. Agent writes code and tests, runs tests, exits with status and summary. Orchestrator commits the changes to the feature branch.

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

### Acceptance Criteria

- [AC-01] WHEN a ticket is in Ready state and an agent slot is available, the sandbox orchestration layer SHALL report a new session for that ticket and stdout SHALL log `ticket <id>: dispatching tdd` with the contract contents.
- [AC-02] WHEN a TDD agent returns an output contract with `status: complete`, stdout SHALL log `ticket <id>: implementing -> awaiting-review`, `git log` on the feature branch SHALL show the orchestrator's commit of the agent's changes, and the ticket SHALL appear in the Awaiting review state in the front end and CLI.
- [AC-11] WHEN an agent exits with `status: blocked`, stdout SHALL log `ticket <id>: blocked, reason: <reason>` and the ticket SHALL appear in the Blocked state in the front end and CLI.
- [AC-14] WHEN a stage is dispatched, the input contract (containing skill name, ticket body, and carry-forward context) SHALL appear in stdout and be visible in the ticket's history in the front end.
- [AC-15] WHEN an agent completes a stage, the output contract (containing status and structured data) SHALL appear in stdout and be visible in the ticket's history in the front end.

### Architectural Constraints

**Module: `platform.agent_client`** — OpenCode HTTP client

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

**Decisions made** (from gap analysis):

- JSON contracts via prompt embed (outbound) and `outcome_path` file (inbound). Skills write structured JSON; orchestrator reads and validates.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.
- Skills are copied from bp-agents `.agents/skills/` into workspace before dispatch.

**Open Risks** (from gap analysis):

- **opencode serve API stability** — The HTTP API is relatively new. Contract shape may change. Version-pin the opencode image.
- **Outcome_path convention** — Skills are instructed to write to `outcome_path`. If a skill doesn't respect this (e.g., writes somewhere else), the orchestrator gets no output. Mitigated by prompt instructions and verified in pipeline tests.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- Secrets must never be logged or written to contracts, traces, or sandbox filesystems.
- The target project must not be this repo (bp-agents)

## This Ticket's Acceptance Criteria

- [ ] `OpenCodeClient` creates a session via opencode serve HTTP API and returns `Session`
- [ ] `OpenCodeClient.prompt()` sends text to the session and receives admission response
- [ ] `OpenCodeClient.stream_events()` yields events from a running session
- [ ] TDD node creates sandbox, dispatches agent with ticket body, waits for completion
- [ ] TDD node reads structured output from `outcome_path` and validates it as `TddOutput`
- [ ] Orchestrator commits agent changes to feature branch of target project after TDD success
- [ ] Input contract (skill, ticket body, context) logged to stdout
- [ ] Output contract (status, summary, test results) logged to stdout
- [ ] Agent-declared blocked (`status: BLOCKED`) transitions ticket to Blocked without commit

## Blocked by

- #02 Tracker port + Pipeline engine skeleton
- #03 Sandbox adapter + Egress proxy

## Outcome

QA stage escalated after 3 rounds. Code is complete and passing all tests (119 unit, 17 integration). All lint passes.

### What was built

- `OpenCodeClient` (httpx wrapper for opencode serve HTTP API): create_session, prompt, stream_events, session_status
- `TddNode`: sandbox creation, agent dispatch with contract logging, outcome_path reading, feature branch creation
- Orchestrator poll loop with Redmine integration: ticket discovery, state transitions (ready → implementing → blocked/awaiting_review)
- Input contracts logged to stdout and posted to Redmine journals (AC-01, AC-14, AC-07 PASS verified)

### Fixes applied in this session

1. **route_ticket routing bug** (`graph.py:120`) — `blocked_reason` routing condition blocked by `status != 'blocked'` guard. Removed guard so blocked reasons route to the `block` node.
2. **ConnectError handler** (`tdd.py`) — Fixed log format to `"blocked, reason: sandbox unreachable"` (AC-11). Added Redmine tracker update before return.
3. **bootstrap env** (`bootstrap_redmine.py`) — Changed empty `BP_TARGET_REPO_PATH` default to match docker-compose default.
4. **gVisor runsc networking** (`docker_sandbox.py`, `config.py`, `main.py`, `docker-compose.yml`) — Three-way reconciliation:

   **Constraint #03:** gVisor netstack doesn't forward UDP on user-defined bridges — Docker DNS (127.0.0.11) uses iptables DNAT rules gVisor doesn't apply (google/gvisor#7469). Fix from #03: default bridge + host gateway proxy.

   **Constraint #04:** Orchestrator on `bp_agents` can't reach sandbox on default bridge. `docker network connect` broken under runsc.

   **Reconciliation:** Sandbox created directly on `bp_agents` network + explicit `dns=["8.8.8.8"]` bypasses Docker DNS + egress-proxy assigned static IP `172.20.0.10` so sandbox reaches proxy by IP without Docker DNS hostname resolution.

   Files changed:
   - `docker-compose.yml` — `bp_agents` network gets explicit subnet (`172.20.0.0/16`), egress-proxy gets `ipv4_address: 172.20.0.10`
   - `config.py` — Added `dns_servers: list[str] | None`, proxy defaults changed to `http://172.20.0.10:8080`
   - `docker_sandbox.py` — Passes `dns` kwarg when `config.dns_servers` is set
   - `main.py` — `network="bp_agents"` already set in previous fix

### What needs human action

**Rebuild and redeploy the orchestrator container** with the latest code (commit `bdb9fcc`) to verify the gVisor networking fix. The code fix is committed and unit-tested, but live E2E verification requires the updated orchestrator to be running.

### Outcome artefacts

- `.scratch/orchestrator/outcomes/implement-outcome.json`
- `.scratch/orchestrator/outcomes/review-outcome.json`
- `.scratch/orchestrator/outcomes/reduction-outcome.json`
- `.scratch/orchestrator/outcomes/verify-outcome.json`
