<!-- Style: headings tight, bullets terse, single lines. No multi-clause sentences. No filler words. -->

# bp-agents

A collection of personal agents.

## Quick Start

```bash
cp .env.example .env
docker compose up
```

## Services

All services start via `docker compose up`.

| Service       | URL                   | Purpose                                      | Credentials                |
| ------------- | --------------------- | -------------------------------------------- | -------------------------- |
| Redmine       | http://localhost:8082  | Ticket tracker (issue management)            | Configure via `.env`       |
| Langfuse      | http://localhost:8083  | LLM observability (traces, evals)            | Configure via `.env`       |
| ClickHouse    | http://localhost:8123  | Columnar DB (required by Langfuse V3/V4)     | None                       |
| egress-proxy  | http://localhost:8081  | mitmproxy web UI (inspect egress traffic)    | None                       |
| Orchestrator  | (logs only)           | LangGraph process driving the SDD pipeline   | None                       |

### Redmine

Issue tracker front-end. Create projects, tickets, and manage the SDD ticket lifecycle. Uses the `redmine:6` image (port 3000 inside container, mapped to 8082 on host).

#### First-time setup

After starting Redmine (`docker compose up`), create an admin user and API key:

1. Open http://localhost:8082 in a browser.
2. Sign in with default credentials: `admin` / `admin`. Change password when prompted.
3. Navigate to **My account → API access key** and show/generate an API key.
4. Copy the API key to `.env` as `REDMINE_API_KEY`.
5. Create a project and note its identifier. Set `REDMINE_PROJECT_ID` in `.env`.
6. Create tickets with status "New" — the orchestrator polls for these as ready tickets.

Redmine's REST API must be enabled. It is on by default. API docs at `http://localhost:8082/projects/<id>/api`.

### Langfuse

LLM tracing and evaluation platform. View agent session content at LLM-conversation level per stage dispatch. Requires ClickHouse (started automatically via `docker compose`).

### ClickHouse

Columnar database required by Langfuse V3/V4. Started automatically alongside Langfuse.

### egress-proxy

mitmproxy web interface at port 8081. Inspect and verify egress traffic against the allowlist.

### Orchestrator

Long-lived LangGraph process. Polls Redmine for ready tickets and dispatches them through the SDD pipeline state machine with SqliteSaver persistence.

## Configuration

Copy `.env.example` to `.env` and fill in secrets. Environment variables are injected into the orchestrator container by Docker Compose.

## Project Structure

```
src/bp_agents/
  platform/        — shared infrastructure (contracts, sandbox, CLI)
  workflows/       — agent-specific workflows (sdd/)
  orchestrator/    — LangGraph process entry point
tests/
  unit/            — unit tests
  integration/     — integration tests
```

## Development

```bash
uv sync           # install dependencies
uv run pytest     # run tests
uv run ruff check # lint
```