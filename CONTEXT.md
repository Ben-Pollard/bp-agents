# bp-agents

A general-purpose agent orchestration platform built on LangGraph. The first workflow is the SDD pipeline: ticket-driven autonomous software development.

## Language

**Orchestrator**:
A long-lived LangGraph process that discovers tickets, dispatches coding agents through a pipeline of skill stages, and merges approved work to main.
_Avoid_: Runner, scheduler, controller

**Pipeline**:
A LangGraph StateGraph defining the sequence of stages a feature flows through. Each stage is a node; edges are conditional on stage outcomes.
_Avoid_: Workflow, DAG

**Stage**:
A single node in the pipeline graph. Dispatches an agent for one skill, waits for completion, reads the output contract, and returns a state delta.
_Avoid_: Step, phase, task

**Ticket**:
A unit of work tracked in Plane, with ID, body, and state. The orchestrator discovers ready tickets via the tracker and drives them through the pipeline.
_Avoid_: Issue, task, card

**Feature**:
A collection of related tickets. The unit of verification and approval. A feature graph contains N ticket subgraphs.
_Avoid_: Epic, story

**Contract**:
Structured JSON exchanged between orchestrator and agent at each stage boundary. Input contracts embed in the prompt; output contracts are written to `outcome_path`.
_Avoid_: Payload, message, envelope

**Sandbox**:
An ephemeral gVisor/Docker container running an opencode agent session. Created per dispatch, destroyed on completion. Has controlled egress via HTTP forward proxy.
_Avoid_: Container, environment, VM

**Dispatch**:
Creating a sandbox, installing skills, prompting opencode with a contract, and monitoring the session until completion or timeout.
_Avoid_: Deploy, launch, spawn

**Tracker**:
The Plane API adapter that discovers ready tickets and updates their state. The orchestrator polls the tracker; the front-end is Plane's own UI.
_Avoid_: Backend, store, database

**Egress policy**:
Network allowlist enforced via HTTP forward proxy. LLM API endpoints, package registries, and MCP endpoints are allowed; all other destinations are blocked and logged.
_Avoid_: Firewall, network rules

**Interrupt**:
LangGraph mechanism pausing graph execution for human input (approve, reject, realign, unblock). Resume via `Command`.
_Avoid_: Pause, halt, await

**outcome_path**:
Filesystem path where the agent writes its output contract JSON. Orchestrator injects this into the prompt; agent creates parent directories if needed.
_Avoid_: Output file, result path

**Skill**:
A markdown instruction file in `.agents/skills/` that defines an agent's behavior for a specific stage (TDD, code review, revision, minimizing-code, verification). Skills define their own output contract schema.
_Avoid_: Prompt, template, instruction set

**Platform**:
The reusable infrastructure layer: LangGraph runner, tracker port, sandbox port, opencode client, CLI framework. Workflow-agnostic.
_Avoid_: Framework, core, engine

**Workflow**:
A specific LangGraph graph built on the platform. The SDD pipeline is the first workflow. New workflows (e.g., data pipeline, doc generation) are future additions.
_Avoid_: Agent, bot, automation

## Relationships

- A **Feature** contains one or more **Tickets**
- An **Orchestrator** runs one **Pipeline** per **Feature**
- A **Pipeline** contains multiple **Stages** connected by edges
- Each **Stage** dispatches one **Skill** in a **Sandbox**
- A **Contract** flows from orchestrator to agent (input) and agent to orchestrator (output)
- The **Tracker** (Plane) owns **Ticket** state; the orchestrator reads and updates it
- **Langfuse** receives traces from both the orchestrator and agent sessions
- **Skills** are copied into the workspace before each **Dispatch**

## Flagged ambiguities

- "agent" was used to mean both the opencode process inside the sandbox and the LangGraph graph itself — resolved: "agent" refers to the opencode process; the graph is the "orchestrator" or "pipeline."