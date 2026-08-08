# Platform

Shared infrastructure that agents compose. Workflow-agnostic.

## Language

**Orchestrator**:
A long-lived LangGraph process that drives a workflow graph. Reads state from external sources, dispatches work, and handles interrupts.
_Avoid_: Runner, scheduler, controller

**Pipeline**:
A LangGraph StateGraph defining a sequence of processing stages connected by conditional edges.
_Avoid_: Workflow, DAG

**Stage**:
A single node in a pipeline graph. Accepts state, performs work (possibly by delegating to an external process), and returns a state delta.
_Avoid_: Step, phase, task

**Contract**:
Structured JSON exchanged at stage boundaries. Input contracts carry state into a stage; output contracts carry results out.
_Avoid_: Payload, message, envelope

**Sandbox**:
An ephemeral gVisor/Docker container running an agent session. Created per dispatch, destroyed on completion. Has controlled egress via HTTP forward proxy.
_Avoid_: Container, environment, VM

**Dispatch**:
Creating a sandbox, configuring it for a session, and monitoring until completion or timeout.
_Avoid_: Deploy, launch, spawn

**Egress policy**:
Network allowlist enforced via HTTP forward proxy. LLM API endpoints, package registries, and approved endpoints are allowed; all other destinations are blocked and logged.
_Avoid_: Firewall, network rules

**Interrupt**:
LangGraph mechanism that pauses graph execution for external input. Execution resumes via `Command`.
_Avoid_: Pause, halt, await


**Skill**:
A markdown instruction file in that defines behaviour for a specific capability. Skills may define their own output contract schema.
_Avoid_: Prompt, template, instruction set

**Platform** (infrastructure):
The reusable infrastructure layer: LangGraph runner, sandbox port, opencode client, CLI framework. Agent-agnostic.
_Avoid_: Framework, core, engine

**Tracker port**:
An abstract interface for discovering and updating units of work from an external system. Each workflow defines its own tracker adapter and work-item model.
_Avoid_: Backend, store, database

