<!-- Style: headings tight, bullets terse, single lines. No multi-clause sentences. No filler words. -->

# bp-agents

A collection of personal agents.

## Quick Start

```bash
cp .env.example .env
```

### 1. Create a target repository

The orchestrator dispatches agents into a **target project** — a separate git repository where the agent will write code and tests. This must NOT be bp-agents itself (enforced by an NFR guard).

```bash
# Outside the bp-agents directory
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

The sandbox image (`symphony-agent:latest`) wraps opencode serve inside a Docker container with minimal tools. Build it from the provided Dockerfile:

```bash
docker build -t symphony-agent:latest -f Dockerfile.sandbox .
```

If you prefer a different tag, set `BP_SANDBOX_IMAGE` in `.env`.

### 3. Configure skills path

Skills are copied from bp-agents into the workspace before dispatch. By default the orchestrator looks at `.agents/skills` **relative to the orchestrator's working directory**. When running via Docker Compose, mount your bp-agents root so this path resolves:

```yaml
volumes:
  - /home/$(whoami)/projects/bp-agents/.agents:/app/.agents:ro
```

Or override with an absolute path in `.env`:

```bash
echo "BP_SKILLS_PATH=/home/$(whoami)/projects/bp-agents/.agents/skills" >> .env
```

### 4. Build and start the stack

```bash
docker compose build orchestrator && docker compose up
```

**Always build before starting.** Source code changes are only reflected if you rebuild. Running without rebuilding runs stale containers. If you modified `Dockerfile.sandbox` or the sandbox configuration, also rebuild the sandbox image (step 2).

To rebuild and restart after code changes:

```bash
docker compose build orchestrator && docker compose up
```

This starts all services including the orchestrator. When the orchestrator finds a `BP_TARGET_REPO_PATH`, it wires the real TDD pipeline. Without it, the stub pipeline runs and blocks tickets with a clear reason.

## Dependencies

### gVisor (runsc)

Docker runtime for agent sandbox isolation. Required for the `platform.sandbox` module (`--runtime=runsc`).

Install via tarball:

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
5. Create a new project (top menu **Administration → Projects → New project**). Choose an identifier (e.g. `my-project`).
6. Set `REDMINE_PROJECT=my-project` in `.env`.
7. Create at least one ticket with status **New** — the orchestrator polls for these as ready tickets.

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