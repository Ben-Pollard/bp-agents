# 03 — OTEL Session Observability

Status: in-progress

## Outcome

All code changes for OTEL Session Observability are complete and verified by passing tests:

**Code implemented:**
- `OtelReceiver` class in `platform/observability/otel_receiver.py` — OTLP/HTTP server on configurable port, protobuf deserialization, log level filtering (info=session events, debug=all spans), best-effort error handling, writes span JSON directly to stdout via `print()` (bypassing Python logging machinery)
- `dispatch()` injects `OTEL_EXPORTER_OTLP_ENDPOINT` env var and `experimental.openTelemetry: true` config
- `agent_config.to_opencode_json()` supports `otel_enabled` flag
- `setup_logging()` in `runner.py` clears and reconfigures root logger to work after uvicorn pre-configuration
- `Dockerfile.sandbox` includes `@opentelemetry/sdk-node` and related npm packages
- `docker-compose.yml` forwards `BP_LOG_LEVEL` (not `LOG_LEVEL`) to orchestrator container
- README updated with `BP_LOG_LEVEL`, `BP_OTEL_PORT`, and observability docs

**Tests:** 176 unit tests + 12 integration tests pass (including 5 OtelReceiver-specific, 9 OTEL pipeline integration, 3 logging setup tests). Lint clean.

**Remaining infrastructure steps for end-to-end verification (requires human action):**
1. Rebuild orchestrator Docker image with latest code (`docker compose build orchestrator && docker compose up -d orchestrator`)
2. Rebuild sandbox Docker image so OTEL npm packages are actually installed (`docker build -f Dockerfile.sandbox -t opencode-agent:latest .`)
3. Create a ticket in Redmine with status "New" to trigger a dispatch
4. Set `BP_LOG_LEVEL=debug` in `.env` and restart orchestrator
5. Verify OTEL spans appear in `docker logs bp-agents-orchestrator-1`

Outcomes:
- IMPLEMENT_OUTCOME: `.scratch/mcp-contract-broker/outcomes/implement-outcome.json`
- REVIEW_OUTCOME: `.scratch/mcp-contract-broker/outcomes/review-outcome.json`
- REDUCTION_OUTCOME: `.scratch/mcp-contract-broker/outcomes/reduction-outcome.json`
- VERIFY_OUTCOME: `.scratch/mcp-contract-broker/outcomes/verify-outcome.json`

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- ADRs: 0001-0005
- Glossary: `CONTEXT.md`

## What Done Means

**Feature-level** (verbatim from the requirements doc):

> I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

**This ticket:** After this ticket, running a dispatch with `BP_LOG_LEVEL=debug` shows all LLM messages and tool calls in orchestrator stdout. At `BP_LOG_LEVEL=info`, only session status changes and errors appear. The traces come from a real opencode agent session — not from synthetic test payloads.

## What to Build

### OtelReceiver

Implement `OtelReceiver` in `platform/observability/otel_receiver.py` per the gap analysis interface. It starts an OTLP/HTTP server on a configurable port that accepts `POST /v1/traces` with OTLP protobuf payloads, deserializes spans, and logs them to stdout at the configured log level:

- `info`: log spans where `event.type` is `session_status` or `session_error`
- `debug`: log all spans including `llm_message` and `tool_call`

The receiver is best-effort — if span deserialization fails or the server errors, the failure is logged and swallowed. It never causes the calling agent session to fail.

### opencode telemetry integration

Enable opencode's native OpenTelemetry support in the sandbox. The preferred path uses opencode's built-in `experimental.openTelemetry` config option + standard OTEL environment variables. If the native path doesn't work (the PR to add full OTEL support is still open), fall back to a community plugin such as `opencode-plugin-otel`.

The opencode.json written by dispatch (issue 05) includes:
```json
{
  "experimental": {
    "openTelemetry": true
  }
}
```

The sandbox environment (issue 05) includes:
```
OTEL_EXPORTER_OTLP_ENDPOINT=http://orchestrator:{otel_port}
```

If a plugin fallback is needed, the plugin is either installed as an npm package in `opencode.json`'s `plugin` array or placed in the sandbox image's global plugin directory.

### Sandbox image dependencies

Ensure `@opentelemetry/sdk-node` and related packages are available in opencode's bun environment inside the sandbox. This may require baking them into the sandbox Docker image or adding them to opencode's global `packages.json`.

### Discovery

The exact span names and attributes from opencode's Vercel AI SDK (`ai.streamText`, `ai.toolCall`, etc.) must be discovered during implementation. The log level filtering rules are adjusted based on what spans opencode actually emits. This is the primary implementation risk — the OTEL native support path may require iteration.

## Requirements

### User Stories

From `docs/requirements/mcp-contract-broker-observability.md`:

> - As a **QA agent**, I want to see LLM messages and tool calls from a failed agent session, so I can determine why the agent failed without re-running the session or reading source code.

### Domain Context

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Session Observability
>
> An opencode plugin emits OpenTelemetry spans for session events (LLM messages, tool calls, errors). Spans are exported via OTLP to the orchestrator's OTEL receiver, which logs them at the configured level:
>
> - `info`: Session status changes and errors only.
> - `debug`: Full LLM message traces for QA investigation.
>
> The QA agent can re-run a failed ticket with `debug` level to see complete session history in orchestrator stdout.

### Behavioral Scenarios

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Scenario: QA debug session visibility
>
> 1. A ticket previously failed the TDD stage. The QA agent wants to see what happened.
> 2. QA agent sets log level to `debug` and re-runs the ticket through the orchestrator.
> 3. Orchestrator stdout shows agent LLM request and response messages for each turn, tool calls and their outputs, and any session errors.
> 4. QA agent identifies the root cause from the message trace without re-running the agent locally or reading source code.

### Acceptance Criteria

From `docs/requirements/mcp-contract-broker-observability.md`:

> - [AC-06] (Scenario: QA debug session visibility) WHERE log level is set to `debug`, orchestrator stdout SHALL include agent LLM request and response messages, tool calls, and session errors for every turn of the agent session.
> - [AC-07] WHERE log level is set to `info`, orchestrator stdout SHALL include session status changes and errors but SHALL NOT include full LLM message content.

### Architectural Constraints

From `docs/architecture/gap-analysis-contract-broker.md`:

**`platform/observability/otel_receiver.py`**:

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

Decisions:

> - **OTEL via opencode native** — `experimental.openTelemetry: true` + `OTEL_EXPORTER_OTLP_ENDPOINT` env var. Preferred path. Fallback: custom opencode OTEL plugin or existing `opencode-plugin-otel`.
> - **OtelReceiver in-process** — runs on dedicated port in orchestrator. Best-effort, never fails agent session.
> - **No new ADRs** — decisions extend existing patterns (Tracker port → schema registry; ephemeral sandbox env → OTEL env vars).

Decisions Deferred:

> - **OTEL span attribute contract** — exact span names and attributes from opencode's AI SDK will be discovered during implementation. Log level filtering rules may need adjustment.

### Testing Decisions

None specific.

### Non-Functional Requirements

From `docs/requirements/mcp-contract-broker-observability.md`:

> - The observability plugin must not cause the agent session to fail if the OTEL receiver is unreachable — logging is best-effort.

### Open Risks

From `docs/architecture/gap-analysis-contract-broker.md`:

> - **OTEL native support uncertainty** — opencode's `experimental.openTelemetry` + OTLP env vars path is documented by collaborators but the PR to add full OTEL support is still open. May need to fall back to a community plugin (`opencode-plugin-otel`) or write a custom one. Discovery needed during implementation.
> - **OTEL SDK in sandbox image** — `@opentelemetry/sdk-node` and dependencies must be available in opencode's bun environment inside the sandbox. May require baking into the sandbox image or adding to opencode's global packages.json.
> - **Span attribute discovery** — span names and attributes from Vercel AI SDK (`ai.streamText`, `ai.toolCall`) may change between opencode versions. Log level filtering rules are coupled to these names.

## This Ticket's Acceptance Criteria

- [ ] `OtelReceiver.start()` serves OTLP/HTTP on port 4318 (configurable)
- [ ] Spans with `event.type=session_status` or `session_error` are logged at `info` level
- [ ] Spans with `event.type=llm_message` or `tool_call` are logged at `debug` level, suppressed at `info`
- [ ] OTEL receiver failures are logged and do not crash the orchestrator
- [ ] opencode in the sandbox emits OTEL spans to the receiver — real agent session, not synthetic
- [ ] At `BP_LOG_LEVEL=debug`, orchestrator stdout shows LLM messages and tool calls from a real dispatch
- [ ] At `BP_LOG_LEVEL=info`, orchestrator stdout shows session status but no full LLM content
- [ ] If the OTEL receiver is down, the agent session still completes successfully (best-effort)

### Canary Test Gates (E2E)

These tests MUST pass in order. Each is a precondition for the next. Any RED test tells you exactly what infrastructure step is missing.

- [ ] `test_sandbox_has_otel_npm_packages` — `@opentelemetry/*` npm packages installed in sandbox image (`tests/e2e/test_otel_observability.py`)
- [ ] `test_orchestrator_otel_receiver_accepts_spans` — OtelReceiver running in orchestrator, accepts OTLP POST (`tests/e2e/test_otel_observability.py`)
- [ ] `test_otel_span_appears_in_orchestrator_logs` — Submitted span JSON appears in `docker logs orchestrator` (`tests/e2e/test_otel_observability.py`)
- [ ] `test_info_level_suppresses_llm_spans_in_logs` — Log level filtering works end-to-end (`tests/e2e/test_otel_observability.py`)

## Blocked by

- 01-code-org-refactor.md