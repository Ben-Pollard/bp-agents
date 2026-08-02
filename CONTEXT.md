# bp-agents

A platform for building and running LangGraph-based agents. Agents share infrastructure; each agent defines its own workflow, domain, and behaviour.

## Structure

- **Platform** (`src/platform/`) — shared infrastructure: sandbox, contracts, CLI, LangGraph runner
- **Workflows** (`src/workflows/`) — agent-specific graphs built on the platform

See `CONTEXT-MAP.md` for the full context layout.