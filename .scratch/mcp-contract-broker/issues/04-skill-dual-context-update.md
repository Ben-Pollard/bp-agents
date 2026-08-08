# 04 — Skill Dual-Context Update

Status: ready-for-human

## Source Documents

- Requirements: `docs/requirements/mcp-contract-broker-observability.md`
- Architecture: `docs/architecture/gap-analysis-contract-broker.md`
- ADRs: 0001-0005
- Glossary: `CONTEXT.md`

## What Done Means

**Feature-level** (verbatim from the requirements doc):

> I submit a ticket to the orchestrator. In the orchestrator stdout, I see a log line confirming a valid contract was accepted. In the tracker UI, I see the ticket has advanced to the next stage. In the target repo, I see a commit with the agent's code. At `debug` log level, I see agent traces — LLM messages and tool calls — for every session.

**This ticket:** After this ticket, the `tdd` skill.md file works correctly in both a local opencode session (writing to `outcome_path`) and the platform sandbox (calling `submit_contract`). A human has reviewed the skill prose. The agent in issue 05 can rely on this skill to deliver contracts via MCP.

## What to Build

Update the `tdd` skill.md file to include a conditional instruction near the contract delivery step. The instruction checks for the `submit_contract` MCP tool:

- If the tool is available: call `submit_contract` with the binding token and the TDD output payload. Do not write `outcome_path`.
- If the tool is not available (local opencode): write the output to `outcome_path` as before.

The conditional is prose in the skill's markdown body — no structured data, no yaml frontmatter changes, no parsing by the platform. The platform does not need to understand the skill's internal logic.

The binding token is provided in the orchestrator's prompt text as a line like `submit_contract token: <token>`. The skill prose instructs the agent to use this token when calling the tool.

Only the `tdd` skill needs updating for this feature. Other skills (code_review, revision, etc.) are updated in their respective future tickets.

This ticket is HITL because the skill prose must be reviewed by a human to ensure:
- The conditional logic is clear and the agent will follow it correctly
- The tool name and parameter names match what the broker exposes
- The fallback path preserves existing local-openode behavior
- The instruction does not introduce ambiguity

## Requirements

### User Stories

From `docs/requirements/mcp-contract-broker-observability.md`:

> - As a **developer**, I want the same skill.md files to work both in my local opencode session and in the platform sandbox, so I can test skills manually before deploying them.

### Domain Context

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Skill Dual-Context Compatibility
>
> Skill.md files must work both in local opencode (no contract-broker) and in the platform sandbox (with contract-broker). Each skill includes a conditional instruction: check for the `submit_contract` tool; if present use it to deliver results; otherwise write to `outcome_path`. The skill file format (yaml frontmatter + markdown) is unchanged — the conditional is prose, not structured data.

### Behavioral Scenarios

From `docs/requirements/mcp-contract-broker-observability.md`:

> ### Scenario: Skill works in both contexts
>
> 1. Developer runs the `tdd` skill locally in their opencode session. The skill checks for `submit_contract` tool — not present. It writes output to `outcome_path`.
> 2. Same skill runs in the platform sandbox. The skill checks for `submit_contract` tool — present. It calls the tool and never writes `outcome_path`.
> 3. In both cases the skill completes successfully. The skill.md file is identical in both contexts.

### Acceptance Criteria

From `docs/requirements/mcp-contract-broker-observability.md`:

> - [AC-08] (Scenario: Skill works in both contexts) WHEN the same skill.md file is used in a sandbox where `submit_contract` is available, the skill SHALL complete by calling the tool without writing to `outcome_path`. WHEN used in a context without the tool, the skill SHALL fall back to writing `outcome_path` and SHALL complete successfully.

### Architectural Constraints

From `docs/architecture/gap-analysis-contract-broker.md`:

> - **Token in prompt** — binding token embedded in skill prompt prose, not opencode.json MCP config.

Prompt format:

> ```
> submit_contract token: {binding_token}
> outcome_path: {outcome_path}  # fallback for local opencode sessions
> ```

### Testing Decisions

None specific.

### Non-Functional Requirements

From `docs/requirements/mcp-contract-broker-observability.md`:

> - The skill.md conditional instruction must not require structured parsing of the markdown file by the platform.

## This Ticket's Acceptance Criteria

- [ ] `tdd` skill.md includes conditional `submit_contract` / `outcome_path` instruction
- [ ] Skill completes successfully in local opencode session (no `submit_contract` tool) by writing `outcome_path`
- [ ] Skill completes successfully in sandbox (with `submit_contract` tool) by calling the tool
- [ ] The same skill.md file is used in both contexts — no platform-specific variants
- [ ] A human has reviewed and approved the skill prose

## Blocked by

- 02-contract-broker-mcp-server.md