<!-- Style: headings tight, bullets terse, single lines. No multi-clause sentences. No filler words. -->

# bp-agents

A platform for building and running LangGraph-based agents. Shared infrastructure (sandbox, contracts, observability, CLI); each agent defines its own workflow graph.

## Workflows

| Workflow | Description | Setup |
| -------- | ----------- | ----- |
| SDD | Ticket-driven autonomous software development | `src/bp_agents/workflows/sdd/` |

## Prerequisites

- Docker (with `docker compose` plugin)
- gVisor (`runsc`) — [install guide](#gvisor-runsc)
- Python 3.13+ (for local dev)

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env — at minimum set OPENROUTER_API_KEY
```

### 2. Build the opencode-agent sandbox image

The sandbox is not a long-running compose service. The orchestrator creates ephemeral sandbox containers on demand — one per agent dispatch, destroyed on completion — using the Docker SDK. The image must be built once ahead of time.

```bash
docker build -t opencode-agent:latest -f Dockerfile.sandbox .
```

### 3. Start all services

```bash
docker compose up -d --build
```

Workflows may need setup before this step (e.g., SDD requires a target repo — see its setup doc first).

This starts:

| Service | Purpose |
|---------|---------|
| orchestrator | LangGraph process dispatching agent sessions |
| redmine / redmine-db / redmine-setup | Ticket tracker — bootstraps on first start (SDD workflow only) |
| langfuse / postgres / clickhouse | LLM observability |
| egress-proxy | Network egress control (allowlist) |

`redmine-setup` runs once to create the admin user, API key, and project. The orchestrator reads the generated credentials on startup.

### 4. Next: run a workflow

See the workflow's setup doc. For SDD: `src/bp_agents/workflows/sdd/README.md`.

## Startup Verification Flow

Diagnostic reference — run individual canary tests when troubleshooting observability issues.

| # | Command | What it proves |
|---|---------|----------------|
| 1 | `uv run pytest tests/e2e/test_otel_observability.py::test_orchestrator_container_is_running` | Container up |
| 2 | `uv run pytest tests/e2e/test_otel_observability.py::test_sandbox_image_exists -v` | Sandbox image built |
| 3 | `uv run pytest tests/e2e/test_otel_observability.py::test_sandbox_has_otel_npm_packages -v` | OTEL SDK available |
| 4 | `uv run pytest tests/e2e/test_otel_observability.py::test_orchestrator_otel_receiver_accepts_spans -v` | OtelReceiver responds |
| 5 | `uv run pytest tests/e2e/test_otel_observability.py::test_otel_span_appears_in_orchestrator_logs -v` | Spans appear in logs |
| 6 | `uv run pytest tests/e2e/test_otel_observability.py::test_info_level_suppresses_llm_spans_in_logs -v` | Filtering works |

## Dependencies

### gVisor (runsc)

Docker runtime for agent sandbox isolation.

```bash
ARCH=$(uname -m)
URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}
wget ${URL}/gvisor.tar.bz2 ${URL}/gvisor.tar.bz2.sha512
sha512sum -c gvisor.tar.bz2.sha512
sudo tar -xjf gvisor.tar.bz2 -C /usr/local/bin
sudo /usr/local/bin/runsc install
sudo systemctl reload docker
```

Verify: `docker run --rm --runtime=runsc hello-world`

## Services

All services start via `docker compose up`.

| Service | URL | Purpose |
| ------- | --- | ------- |
| Orchestrator | (logs only) | LangGraph process driving workflows |
| egress-proxy | http://localhost:8081 | mitmproxy web UI (inspect egress) |
| Langfuse | http://localhost:8083 | LLM observability |
| ClickHouse | http://localhost:8123 | Columnar DB (Langfuse backend) |
| Redmine | http://localhost:8082 | Ticket tracker (SDD workflow only) |

### Orchestrator

Long-lived LangGraph process. Runs `src/bp_agents/main.py` inside the container. Registers workflow graphs, starts tracker pollers, dispatches sandbox sessions. State persisted via SqliteSaver.

### Langfuse

LLM tracing. Requires ClickHouse (auto-started).

## Observability

The orchestrator runs an OTLP/HTTP receiver (`OtelReceiver`) on port `BP_OTEL_PORT` (default 4318). Agent sessions emit OpenTelemetry spans via OTEL SDK to `http://orchestrator:{BP_OTEL_PORT}/v1/traces`.

**Log level filtering:**

| `BP_LOG_LEVEL` | Spans shown in stdout |
|---------------|----------------------|
| `info` | `session_status`, `session_error` only |
| `debug` | All spans including `llm_message`, `tool_call` |

Set `BP_LOG_LEVEL=debug` in `.env` for full LLM message traces.

## Configuration

Copy `.env.example` to `.env` and fill in secrets. Injected by Docker Compose.

| Variable | Default | Purpose |
|----------|---------|---------|
| `BP_LOG_LEVEL` | `info` | Orchestrator log level. `debug` for full OTEL output |
| `BP_OTEL_PORT` | `4318` | OTLP/HTTP receiver port |
| `BP_MCP_PORT` | `8001` | Contract broker MCP port |
| `BP_POLL_INTERVAL` | `5` | Tracker poll interval (seconds) |
| `BP_PIPELINE_DB_PATH` | `pipeline_checkpoints.db` | Sqlite checkpoint path |
| `BP_SANDBOX_IMAGE` | `opencode-agent:latest` | opencode sandbox image |
| `BP_SANDBOX_RUNTIME` | `runsc` | gVisor runtime |
| `BP_SKILLS_PATH` | `.agents/skills` | Skill directories path |

Workflow-specific variables (SDD): see `src/bp_agents/workflows/sdd/README.md`.

## Project Structure

```
src/bp_agents/
  platform/        — shared infrastructure (contracts, sandbox, CLI)
  workflows/       — agent-specific workflows (sdd/)
  orchestrator/    — LangGraph entry point
  main.py          — orchestrator startup
tests/
  unit/            — unit tests
  integration/     — integration tests (real HTTP, no Docker)
  e2e/             — end-to-end tests (real Docker containers)
```

## Development

```bash
uv sync                        # install deps
uv run pytest                  # run all tests (skips e2e by default)
uv run pytest -m e2e           # run e2e tests only
uv run pytest -m "not e2e"     # run everything except e2e
uv run ruff check              # lint
```