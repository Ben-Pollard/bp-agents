# 10 — Contract fulfillment fixes and state-audit hardening

Status: ready-for-agent

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- Glossary: `CONTEXT.md`

## What Done Means

A hello-world ticket dispatched from Redmine completes its TDD stage via MCP contract submission, and Redmine's UI shows the same status the orchestrator holds, with a complete activity history — no direct DB writes, no lost journals.

## What to Build

Three fixes. Order matters: 1 then 2 then 3.

### 1. Thread the ContractBroker through the dispatch pipeline

Issue 02 built `ContractBroker` and the FastMCP server, but `main.py` creates the broker and never passes it onward. The runtime path never sees it.

- `main.py` creates `broker` (`main.py:111`) but `build_ticket_pipeline()` has no `broker` parameter.
- `graph.py:build_ticket_pipeline` → `TddNode.__init__` → `TddNode.__call__` → `dispatch()`: add a `broker` parameter at each level and pass it through.
- `dispatch()` already accepts `broker` and calls `create_binding`/`submit` (`dispatch.py:124`, `:190`, `:276`), but `broker=None` always reaches it.
- Bind the MCP server to `0.0.0.0`, not `127.0.0.1` (`main.py` MCP startup). The sandbox is a separate container on the `bp_agents` network and cannot reach the orchestrator's loopback.
- Inject the broker MCP URL into the sandbox `opencode.json` via `mcp_defs` (currently `{}` in `dispatch.py`), so the agent can discover `submit_contract`.
- Pass the binding token to the sandbox via `CONTRACT_BROKER_TOKEN` (code exists at `dispatch.py:199`; unreachable until broker is threaded).

### 2. Make contract submission not depend on an outcome file

`dispatch()` raises `FileNotFoundError` when `outcome.json` is missing, *before* reaching `broker.submit`. The MCP path must work without the file.

- `dispatch.py` outcome handling: when `broker is not None`, treat MCP submission as the primary fulfilment path and the file as an optional fallback.
- The file check must not be a hard prerequisite when a broker is configured. Absence of both file *and* MCP submission is the only case that blocks.

### 3. Remove the Redmine direct-DB status write; configure workflow transitions

`tracker.update_state()` does a REST `PUT` (allowed by workflow → creates a journal) *and then* a direct SQL `UPDATE issues SET status_id = ...` (`tracker.py:_db_update_status`) that bypasses workflow validation and journaling. This is the source of the UI/workflow state misalignment: the status changes but no activity entry is written.

- Remove `_db_update_status` (and its `REDMINE_DB_SKIP` / `REDMINE_DB_URL` plumbing) once the PUT path is reliable.
- Configure Redmine workflow transitions so the SDD statuses accept the `PUT`s. `bootstrap_redmine.py` and `tracker.ensure_statuses()` create statuses but configure no transitions — that is why the new-issue form only offers `ready`, and why earlier workaround was needed.
- Add a bootstrap step (Rails runner, like the existing admin/status setup) that inserts transition rows allowing the SDD states to move in the pipeline order: `ready → implementing → awaiting_review → reviewing → awaiting_verification → verifying → awaiting_approval → done`, plus the revision and blocked branches.

## Acceptance Criteria

- [ ] `broker` reaches `dispatch()` with `broker is not None` for an SDD TDD run
- [ ] The MCP server binds `0.0.0.0` and is reachable from a sandbox container
- [ ] The sandbox `opencode.json` contains the broker MCP server entry
- [ ] A ticket whose agent submits the contract via `submit_contract` and writes no `outcome.json` advances to `awaiting_review`
- [ ] A ticket whose agent does neither (no MCP submission, no file) still blocks with `agent: no contract submitted`
- [ ] `tracker.update_state()` performs no direct SQL against the Redmine DB
- [ ] Redmine's issue activity history shows every status transition with author and timestamp
- [ ] Redmine UI status always matches the orchestrator's LangGraph state
- [ ] Hello-world end-to-end: `ready → implementing → awaiting_review` with a visible journal per transition

## Blocked by

None.
