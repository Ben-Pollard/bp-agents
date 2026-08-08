# MCP Contract Broker & Session Observability

> Last updated: 2026-08-08

## Problem Statement

When an opencode agent runs inside a sandbox, it must deliver a structured contract (e.g. TDD output, review output) back to the orchestrator. Today that contract is written as a JSON file (`outcome.json`) to the workspace, which the dispatch function reads after the agent exits. Two problems:

1. **Agent struggles to produce conformant output.** After a long-running session the opencode agent often writes an invalid or missing outcome file. There is no feedback loop — the agent discovers the mistake only after its session ends, when it's too late to correct.

2. **When the agent fails, we are blind.** The sandbox is destroyed on failure, taking all session context with it. The QA agent cannot see what happened inside the agent session because no persistent log of LLM messages, tool calls, or errors survives sandbox teardown.

The contract delivery mechanism must give the agent real-time validation feedback during its session, and the system must retain agent session content so failures are debuggable without reading source code or re-running sessions.

## Solution

Replace file-based contract delivery with an MCP (Model Context Protocol) tool that the agent calls during its session. A platform-hosted **contract-broker** MCP server validates contracts against the workflow's Pydantic schemas in real time, returning acceptance or structured validation errors that the agent can correct within the same session. The agent's task is complete once the contract-broker accepts a submission — no file write, no `outcome_path`.

For debuggability, the opencode session events (LLM messages, tool calls, errors) are streamed out of the sandbox via an observability plugin that emits OpenTelemetry spans to the orchestrator. Log level controls verbosity: `info` for session status and errors only; `debug` for full message traces that the QA agent uses to investigate failures.

The contract-broker is platform infrastructure — one long-lived server that serves all workflows. Workflow-specific contract schemas (Pydantic models) are defined in the workflow's contracts module and serve as the single source of truth for both MCP validation and LangGraph node parsing.

## Definition of Done

I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

## User Stories

- As a **developer**, I want the agent to receive immediate feedback when its contract output doesn't match the required schema, so it can correct mistakes during the session rather than failing silently.
- As a **QA agent**, I want to see LLM messages and tool calls from a failed agent session, so I can determine why the agent failed without re-running the session or reading source code.
- As a **developer**, I want contract schemas defined once as Pydantic models that both the MCP server and LangGraph nodes use, so there is no schema drift between what the agent must produce and what the graph expects.
- As a **developer**, I want the same skill.md files to work both in my local opencode session and in the platform sandbox, so I can test skills manually before deploying them.
- As a **developer**, I want the contract-broker to be platform infrastructure reusable by all workflows, so I don't rebuild contract validation for each new agent.

## Domain Context

### Contract-Broker MCP Server

A long-lived MCP server hosted in the orchestrator process. Exposes one or more tools that agents call to submit their stage output. The broker validates submissions against workflow-defined Pydantic schemas and either accepts or returns structured validation errors.

**Per-dispatch binding**: Each sandbox dispatch is bound to a specific workflow, stage, and run. The agent cannot choose or change the target schema — the binding is established by the orchestrator at dispatch time and expires when the sandbox session ends.

**Validation retry**: The agent may submit an invalid contract and receive validation errors. The broker allows a configurable number of failed attempts per run (default: 3). On the final attempt, the broker returns a terminal error instructing the agent to stop. The agent's own max-turns and timeout are backstop limits underneath the broker's retry cap.

**Lock-on-success**: Once the broker accepts a valid submission for a run, further submissions for that run are rejected. This prevents a confused agent from overwriting a good contract with a worse one later in the same session.

### Agent-Loop Retry vs Node-Level Retry

Two distinct retry layers:

- **Agent-loop retry** (inside the sandbox): The contract-broker validates and returns errors to the agent. The agent corrects and resubmits — full session context is preserved. Handles invalid contracts.
- **Node-level retry** (LangGraph): Handles transport failures (sandbox unreachable, timeout) via LangGraph's `retry_policy`, `timeout`, and `error_handler` on `add_node()`. The error handler updates the tracker to reflect blocked/failed status after retries are exhausted.

The TDD node no longer has its own retry loop. Contract status values (DONE, BLOCKED, FAIL) are routing signals for the graph, not retry triggers.

### Dispatch Flow

The `dispatch()` function changes from file-read to event-driven:

1. Write opencode.json (includes contract-broker MCP URL and per-dispatch binding)
2. Create sandbox, health check, inject credentials, create session, send prompt
3. Await either a valid contract submission (broker event) or a timeout
4. On contract event: abort session, return validated contract
5. On timeout: destroy sandbox, raise failure (handled by LangGraph retry)

The `outcome_path` environment variable and `OUTCOME_FILENAME` constant become obsolete for contract delivery.

### Session Observability

An opencode plugin emits OpenTelemetry spans for session events (LLM messages, tool calls, errors). Spans are exported via OTLP to the orchestrator's OTEL receiver, which logs them at the configured level:

- `info`: Session status changes and errors only.
- `debug`: Full LLM message traces for QA investigation.

The QA agent can re-run a failed ticket with `debug` level to see complete session history in orchestrator stdout.

### Skill Dual-Context Compatibility

Skill.md files must work both in local opencode (no contract-broker) and in the platform sandbox (with contract-broker). Each skill includes a conditional instruction: check for the `submit_contract` tool; if present use it to deliver results; otherwise write to `outcome_path`. The skill file format (yaml frontmatter + markdown) is unchanged — the conditional is prose, not structured data.

### Code Organisation

The platform/workflow split is enforced in code layout:

```
src/bp_agents/
├── main.py                  # Entry point: loads config, wires platform + workflows
├── platform/                # Shared infra, workflow-agnostic
│   ├── CONTEXT.md
│   ├── runner.py            # General-purpose LangGraph runtime
│   ├── dispatch.py
│   ├── agent_client.py
│   ├── agent_config.py
│   ├── tracker.py           # Abstract tracker port
│   ├── mcp/
│   │   └── contract_broker.py
│   ├── observability/
│   │   └── otel_receiver.py
│   └── sandbox/
│       ├── base.py
│       ├── config.py
│       ├── docker_sandbox.py
│       └── egress.py
└── workflows/               # Agent-specific graphs
    ├── CONTEXT.md
    └── sdd/
        ├── CONTEXT.md
        ├── contracts.py     # Pydantic models (was TypedDicts)
        ├── graph.py
        ├── state.py
        ├── skill_configs.py
        ├── tracker.py       # RedmineTracker
        └── nodes/
            └── tdd.py
```

## Behavioral Scenarios

### Scenario: Happy path — agent submits valid contract via MCP

1. Orchestrator poll finds a ready ticket, routes it to the SDD pipeline graph.
2. The TDD node calls `dispatch()`, which creates a sandbox and sends the TDD prompt (including the contract-broker MCP URL and per-dispatch binding).
3. The agent writes code and tests, then calls `submit_contract` with a valid `TddOutput` payload.
4. The contract-broker validates the payload against the `TddOutput` Pydantic model, accepts it, and signals the dispatcher.
5. `dispatch()` logs the accepted contract to stdout, aborts the agent session, and returns the validated contract to the TDD node.
6. The TDD node commits the agent's changes to the feature branch, logs the state transition, and the ticket advances to Awaiting review.
7. The `outcome.json` file is never written to the workspace.

### Scenario: Invalid contract, agent retries and succeeds

1. Agent calls `submit_contract` with a payload missing the `test_results` field.
2. Contract-broker rejects with validation errors: "Missing required field: test_results."
3. Agent sees the error, corrects the payload, calls `submit_contract` again.
4. This time the broker accepts the payload.
5. Orchestrator stdout logs show: attempt 1 (rejected), attempt 2 (accepted). Ticket advances normally.

### Scenario: Max validation retries exhausted

1. Agent calls `submit_contract` with an invalid payload.
2. Broker rejects with validation errors. Agent resubmits — still invalid.
3. Agent resubmits a third time — still invalid. This is the final allowed attempt.
4. Broker returns a terminal error: "Max attempts exceeded, stop and end session."
5. `dispatch()` logs the terminal error to stdout. The agent session is aborted.
6. The TDD node's error handler updates the tracker: ticket transitions to Blocked with reason "agent: contract validation failed after 3 attempts."

### Scenario: Lock-on-success prevents overwrite

1. Agent calls `submit_contract` with a valid payload. Broker accepts.
2. Agent (confused) calls `submit_contract` again during the same session.
3. Broker rejects: "Run already has an accepted submission."
4. `dispatch()` returns only the first accepted contract. The second rejection is logged at info level.

### Scenario: QA debug session visibility

1. A ticket previously failed the TDD stage. The QA agent wants to see what happened.
2. QA agent sets log level to `debug` and re-runs the ticket through the orchestrator.
3. Orchestrator stdout shows agent LLM request and response messages for each turn, tool calls and their outputs, and any session errors.
4. QA agent identifies the root cause from the message trace without re-running the agent locally or reading source code.

### Scenario: Skill works in both contexts

1. Developer runs the `tdd` skill locally in their opencode session. The skill checks for `submit_contract` tool — not present. It writes output to `outcome_path`.
2. Same skill runs in the platform sandbox. The skill checks for `submit_contract` tool — present. It calls the tool and never writes `outcome_path`.
3. In both cases the skill completes successfully. The skill.md file is identical in both contexts.

### Scenario: Dispatch timeout with no contract

1. Orchestrator dispatches a TDD agent with a 30-minute timeout.
2. Agent runs for 30 minutes without submitting a valid contract.
3. `dispatch()` times out, destroys the sandbox, and raises a timeout exception.
4. LangGraph's `retry_policy` retries the node. If retries are exhausted, LangGraph's `error_handler` runs: updates tracker, ticket transitions to Blocked with "auto: stage timeout."

## Acceptance Criteria

### Contract delivery

- [AC-01] (Scenario: Happy path) WHEN an agent calls `submit_contract` with a valid payload, orchestrator stdout SHALL log the accepted contract with ticket ID, stage, and run ID, and the ticket SHALL transition from the dispatched stage to the next stage in the pipeline.
- [AC-02] (Scenario: Happy path) WHEN a valid contract is accepted, the `outcome.json` file SHALL NOT appear in the workspace.

### Validation retry

- [AC-03] (Scenario: Invalid contract, agent retries and succeeds) WHEN the agent submits an invalid contract, orchestrator stdout SHALL log the rejection with validation errors. IF the agent resubmits a valid payload on a subsequent attempt, stdout SHALL log the accepted contract and the ticket SHALL advance.
- [AC-04] (Scenario: Max validation retries exhausted) WHEN the agent exhausts the allowed validation attempts, orchestrator stdout SHALL log a terminal error ("max attempts exceeded"), the agent session SHALL end, and the ticket SHALL appear in the Blocked state with a reason indicating contract validation failure.

### Lock-on-success

- [AC-05] (Scenario: Lock-on-success prevents overwrite) WHEN a valid contract has already been accepted for a run, any subsequent `submit_contract` call SHALL be rejected, stdout SHALL log the rejection ("already submitted"), and ONLY the first accepted contract SHALL be delivered to the LangGraph node.

### Observability

- [AC-06] (Scenario: QA debug session visibility) WHERE log level is set to `debug`, orchestrator stdout SHALL include agent LLM request and response messages, tool calls, and session errors for every turn of the agent session.
- [AC-07] WHERE log level is set to `info`, orchestrator stdout SHALL include session status changes and errors but SHALL NOT include full LLM message content.

### Skill compatibility

- [AC-08] (Scenario: Skill works in both contexts) WHEN the same skill.md file is used in a sandbox where `submit_contract` is available, the skill SHALL complete by calling the tool without writing to `outcome_path`. WHEN used in a context without the tool, the skill SHALL fall back to writing `outcome_path` and SHALL complete successfully.

### Dispatch flow

- [AC-09] (Scenario: Dispatch timeout with no contract) WHEN a dispatched agent session reaches its timeout without a valid contract submission, orchestrator stdout SHALL log the timeout, the sandbox SHALL be destroyed, and the ticket SHALL either retry (if retries remain) or transition to Blocked (if retries exhausted) with "stage timeout" in the reason.

### Code organisation

- [AC-10] The contract-broker MCP server SHALL reside under `src/bp_agents/platform/mcp/`. Workflow contract models SHALL be Pydantic `BaseModel` classes under the workflow's `contracts.py`. The `src/platform/` and `src/workflows/` stub directories SHALL NOT exist.

### Contract schemas as single source of truth

- [AC-11] The same Pydantic model class SHALL be used by the contract-broker for MCP tool input validation AND by the LangGraph node for parsing the returned contract. Discrepancy between the MCP schema and the graph's expected schema SHALL NOT be possible without a code change visible in the same file.

## Non-Functional Requirements

- Contract-broker validation must not introduce perceptible latency beyond normal MCP tool call overhead (sub-second for Pydantic validation).
- Per-dispatch bindings (tokens) must not be reusable across sandbox sessions and must not grant access to contracts from other runs.
- The observability plugin must not cause the agent session to fail if the OTEL receiver is unreachable — logging is best-effort.
- The skill.md conditional instruction must not require structured parsing of the markdown file by the platform.
- The contract-broker must not persist contracts to disk — contracts live in memory for the duration of the dispatch call only.

## Out of Scope

- Replacing `outcome_path` for non-contract purposes (e.g., agent writing arbitrary files to workspace is unchanged).
- Full Langfuse integration — that belongs to the observability ticket. OTEL spans exported to orchestrator stdout are the interim solution.
- Contract schemas beyond those already in the SDD workflow (TddOutput, ReviewOutput, RevisionOutput).
- MCP servers other than the contract-broker (Context7, Playwright hosting pattern is identified but not implemented here).
- Agent-in-sandbox model changes for workflows beyond SDD.
- Converting existing skill.md files to reference `submit_contract` — that is an implementation step, not a new requirement.

## Priority

**High.** The contract reliability problem blocks issue 4 from passing QA. The observability gap blocks the QA agent from diagnosing failures. This is a prerequisite for completing the SDD pipeline's TDD stage reliably.

## Changelog