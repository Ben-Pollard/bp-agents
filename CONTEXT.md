# bp-agents

A platform for building and running LangGraph-based agents. Agents share infrastructure; each agent defines its own workflow, domain, and behaviour.

## Structure

- **Platform** (`src/platform/`) — shared infrastructure: sandbox, contracts, CLI, LangGraph runner
- **Workflows** (`src/workflows/`) — agent-specific graphs built on the platform

## Glossary

- **Contract-Broker** — in-process MCP server (FastMCP) that validates agent stage output against workflow-registered Pydantic schemas. Manages per-dispatch bindings with retry caps and lock-on-success.
- **Binding** — ephemeral token scoped to (workflow, stage, run_id). Created by `dispatch()`, invalidated on acceptance or session end.
- **Schema Registry** — runtime registration of workflow Pydantic models with the contract-broker. Preserves platform → workflow dependency prohibition.