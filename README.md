<!-- Style: headings tight, bullets terse, single lines. No multi-clause sentences. No filler words. -->

# bp-agents

A collection of personal agents.

## Prerequisites

- Docker (with `docker compose` plugin)
- gVisor (`runsc`) — [install guide](#gvisor-runsc)
- Python 3.13+ (for local dev)

## Quick Start

### 0. Clone and configure

```bash
cp .env.example .env
# Edit .env — at minimum set OPENROUTER_API_KEY
```

### 1. Create a target repository

The orchestrator dispatches agents into a **target project** — a separate git repository where the agent writes code and tests. This must NOT be bp-agents itself.

```bash
mkdir -p ~/projects/my-project
cd ~/projects/my-project
git init -b main
git commit --allow-empty -m "initial"
echo "# My Project" > README.md
git add README.md && git commit -m "add readme"
```

Set the absolute path in `.env`:

```bash
echo "BP_TARGET_REPO_PATH=/home/$(whoami)/projects/my-project" >> .env
```

### 2. Build the sandbox image

The sandbox wraps opencode serve with OTEL SDK for span export.

```bash
docker build -t symphony-agent:latest -f Dockerfile.sandbox .
```

**Verify:** Run `tests/e2e/test_otel_observability.py::test_sandbox_has_otel_npm_packages`. It checks `@opentelemetry/*` packages exist. GREEN means ready.

```bash
uv run pytest tests/e2e/test_otel_observability.py::test_sandbox_has_otel_npm_packages -v
```

If RED, the Dockerfile.sandbox `npm install -g` line may have failed. Check build output and rebuild.

### 3. Configure skills path

Skills are copied from bp-agents into the workspace. Set in `.env`:

```bash
echo "BP_SKILLS_PATH=$(pwd)/.agents/skills" >> .env
```

### 4. Build and start the orchestrator

```bash
docker compose build orchestrator && docker compose up -d orchestrator
```

This builds the orchestrator image with latest code. The `compose up` starts all services.

**Verify:** Run the orchestrator canary tests. They prove OtelReceiver is running and spans appear in stdout.

```bash
# Must pass before any OTEL observability works
uv run pytest tests/e2e/test_otel_observability.py -v -k "orchestrator"
```

### 5. Configure Redmine

Set up the ticket tracker so the orchestrator has work to dispatch.

First, ensure Redmine is running:

```bash
docker compose up -d redmine-db redmine redmine-setup
```

Then:

1. Open http://localhost:8082 in a browser.
2. Sign in: `admin` / `admin`. Change password when prompted.
3. **My account → API access key** → show/generate → copy to `.env` as `REDMINE_API_KEY`.
4. **Administration → Projects → New project**. Identifier: `my-project`.
5. Set `REDMINE_PROJECT=my-project` in `.env`.
6. **Administration → Statuses** — ensure the status names match `skills/triage/skill.md` (default import handles this).
7. Create a ticket with status **New**.

**Verify:** Run the Redmine E2E test to confirm the tracker can find tickets.

```bash
uv run pytest tests/e2e/test_redmine_tracker.py -v
```

### 6. Start the orchestrator pipeline

```bash
docker compose up -d orchestrator
```

The orchestrator polls Redmine every 5 seconds. When it finds a ticket in status **New**, it dispatches through the SDD pipeline.

**Verify the full OTEL pipeline:**

```bash
uv run pytest tests/e2e/test_otel_observability.py -v
```

All 5 canary tests should be GREEN. If any are RED, follow the error message — it tells you exactly what infrastructure step is missing.

## Startup Verification Flow

Run these in order to diagnose pipeline issues:

| Step | Command | What it proves |
|------|---------|----------------|
| 1 | `uv run pytest tests/e2e/test_otel_observability.py::test_orchestrator_container_is_running` | Container is up |
| 2 | `uv run pytest tests/e2e/test_otel_observability.py::test_sandbox_image_exists -v` | Sandbox image is built |
| 3 | `uv run pytest tests/e2e/test_otel_observability.py::test_sandbox_has_otel_npm_packages -v` | OTEL SDK available |
| 4 | `uv run pytest tests/e2e/test_otel_observability.py::test_orchestrator_otel_receiver_accepts_spans -v` | OtelReceiver responds |
| 5 | `uv run pytest tests/e2e/test_otel_observability.py::test_otel_span_appears_in_orchestrator_logs -v` | Spans appear in logs |
| 6 | `uv run pytest tests/e2e/test_otel_observability.py::test_info_level_suppresses_llm_spans_in_logs -v` | Filtering works |

After all 6 pass, the OTEL observability pipeline works. Create a Redmine ticket with status **New** and the orchestrator will dispatch it.

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

| Service       | URL                   | Purpose                                      |
| ------------- | --------------------- | -------------------------------------------- |
| Redmine       | http://localhost:8082  | Ticket tracker                               |
| Langfuse      | http://localhost:8083  | LLM observability                            |
| ClickHouse    | http://localhost:8123  | Columnar DB (Langfuse V3/V4)                 |
| egress-proxy  | http://localhost:8081  | mitmproxy web UI (inspect egress)            |
| Orchestrator  | (logs only)           | LangGraph process driving SDD pipeline       |

### Redmine

Issue tracker. Uses `redmine:6` (port 3000 inside, 8082 on host).

### Langfuse

LLM tracing. Requires ClickHouse (auto-started).

### Orchestrator

Long-lived LangGraph process. Polls Redmine for ready tickets, dispatches through SDD pipeline. State persisted via SqliteSaver.

### Observability

The orchestrator runs an OTLP/HTTP receiver (`OtelReceiver`) on port `BP_OTEL_PORT` (default 4318). Agent sessions emit OpenTelemetry spans via OTEL SDK to `http://orchestrator:{BP_OTEL_PORT}/v1/traces`.

**Log level filtering:**

| `BP_LOG_LEVEL` | Spans shown in stdout |
|---------------|----------------------|
| `info` | `session_status`, `session_error` only |
| `debug` | All spans including `llm_message`, `tool_call` |

Set `BP_LOG_LEVEL=debug` in `.env` for full LLM message traces. Proves [AC-06] and [AC-07].

## Configuration

Copy `.env.example` to `.env` and fill in secrets. Injected by Docker Compose.

| Variable | Default | Purpose |
|----------|---------|---------|
| `BP_LOG_LEVEL` | `info` | Orchestrator log level. `debug` for full OTEL output. |
| `BP_OTEL_PORT` | `4318` | OTLP/HTTP receiver port. |
| `BP_POLL_INTERVAL` | `5` | Redmine poll interval (seconds). |
| `BP_PIPELINE_DB_PATH` | `pipeline_checkpoints.db` | Sqlite checkpoint path. |
| `BP_SANDBOX_IMAGE` | `symphony-agent:latest` | Docker image for agent sandbox. |
| `BP_TARGET_REPO_PATH` | — | Absolute path to target git repo. |
| `BP_SKILLS_PATH` | `.agents/skills` | Skill directories path. |
| `BP_SANDBOX_RUNTIME` | `runsc` | gVisor runtime. |
| `BP_MCP_PORT` | `8001` | Contract broker MCP port. |
| `REDMINE_BASE_URL` | `http://redmine:3000` | Redmine API URL. |
| `REDMINE_API_KEY` | — | Redmine API key. |
| `REDMINE_PROJECT` | `default` | Redmine project identifier. |

## Project Structure

```
src/bp_agents/
  platform/        — shared infrastructure (contracts, sandbox, CLI)
  workflows/       — agent-specific workflows (sdd/)
  orchestrator/    — LangGraph entry point
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