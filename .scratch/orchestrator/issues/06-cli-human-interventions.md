Status: ready-for-agent

# 06 — CLI + Human interventions

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001
- Glossary: `CONTEXT.md`

## What to Build

CLI framework (`platform.cli`) with registered actions. Implement all four human intervention commands against the running orchestrator (via LangGraph interrupt/resume):

- `symphony approve <ticket-id>` — merge branch to main, transition to Done
- `symphony reject <ticket-id> --reason "..."` — reject with reason, transition back to Implementing
- `symphony realign <ticket-id> --acs "..."` — record AC changelog entry (ADDED/MODIFIED/REMOVED), transition back to Implementing with new ACs
- `symphony unblock <ticket-id> [--note "..."]` — resume at blocked stage
- `symphony status [<ticket-id>]` — show current state

All actions logged to stdout with user, timestamp, and reason. Every action appears in ticket intervention history. AC changelog tracks realignments.

## Requirements

### User Stories

- As a **developer**, I want to approve or reject completed work through the orchestrator, so merges to main are auditable system events.
- As a **developer**, I want to unblock stalled tickets with instructions or code changes, so the system resumes without restarting from scratch.
- As a **developer**, I want to request realignment when requirements change mid-ticket, so the system reworks from new ACs and records the change.

### Domain Context

**Human Interventions** (from reqs doc):

Four actions, available via CLI and dashboard:

- **Approve** — merge branch to main, transition to Done.
- **Reject** — reject with reason; transition back to TDD with reason in contract.
- **Realign** — modify ACs, transition back to TDD; record a redefinition event with AC diff, timestamp, and who triggered it.
- **Unblock** — provide resolution (code change, instructions, review override), transition back to the stage where blocked.

Redefinition events are stored per ticket as a changelog. Later analysis can correlate AC churn with escalation/blocking events.

Blocked is triggered when:
- A stage exhausts its retry limit (automatic).
- An agent declares it cannot proceed in its output contract (agent-declared).

The reason field distinguishes the source.

**Agent → Blocked → Agent Cycle (Max Retries)** (from reqs doc):

When a stage reaches its retry limit, the system transitions to Blocked. The developer unblocks via one of:
- Modifying code directly (e.g., in an interactive agent session on the branch).
- Providing instructions for an orchestrator-managed agent to resolve the conflict (clarifying an ambiguity, modifying ACs, sending a code review pass event).
- Requesting realignment with new ACs.

After unblocking, the orchestrator resumes at the blocked stage.

### Behavioral Scenarios

**Scenario: Human rejects with reason**

1. Ticket reaches Awaiting approval. Developer reviews the diff.
2. Developer finds the implementation missed a requirement, runs `symphony reject hello-1 --reason "No validation on null input as per AC-04"`.
3. Orchestrator records rejection event, transitions to Implementing (back to TDD).
4. Orchestrator creates a fresh TDD branch, dispatches TDD agent with rejection reason in contract.
5. Agent implements the fix. Orchestrator commits. Pipeline runs through all stages again.

**Scenario: Human requests realignment**

1. Ticket reaches Awaiting approval. Developer realizes the ACs are wrong.
2. Developer runs `symphony realign hello-1` with updated ACs (AC-04 added, AC-05 modified).
3. Orchestrator records redefinition event: `AC-04 ADDED, AC-05 MODIFIED: inputs over 1MB must raise ValidationError`. Timestamp and actor recorded.
4. Orchestrator transitions to Implementing, creates a fresh branch, dispatches TDD agent with new ACs in contract.
5. Pipeline runs from start with updated requirements.

**Scenario: Max retries exhausted, human unblocks**

1. TDD agent fails (e.g., test failure after implementation). Orchestrator retries.
2. Retry 1 fails. Retry 2 fails. Retry limit of 3 reached.
3. Orchestrator transitions to Blocked with reason "auto: max retries (3) exhausted for TDD stage."
4. Developer investigates, modifies code on the feature branch directly.
5. Developer runs `symphony unblock hello-1 --note "Fixed import path"`.
6. Orchestrator transitions to Awaiting review (TDD was completed from prior retries; work is on branch).
7. Pipeline resumes from code review stage.

### Acceptance Criteria

- [AC-08] WHEN a human rejects a ticket with a reason, stdout SHALL log `ticket <id>: rejected by <user>, reason: <reason>`, the rejection SHALL appear in the ticket's history in the front end, and the sandbox orchestration layer SHALL report a new TDD session.
- [AC-09] WHEN a human realigns a ticket with updated ACs, stdout SHALL log a redefinition event containing the AC diff and actor, and the ticket's AC changelog (visible in the front end) SHALL contain a new entry with the same diff.
- [AC-10] WHEN a human unblocks a ticket, stdout SHALL log `ticket <id>: unblocked by <user>` and the sandbox orchestration layer SHALL report a new session for the stage where the ticket was blocked.
- [AC-29] WHEN a human performs an approve, reject, realign, or unblock action, stdout SHALL log the action with user, timestamp, and reason, and the action SHALL appear in the ticket's intervention history in the front end.
- [AC-30] WHEN a realignment occurs, the ticket's AC changelog (queryable in the front end) SHALL show what was added, modified, or removed, with timestamp and actor.
- [AC-33] The CLI or action surface SHALL accept and confirm approve, reject, realign, and unblock commands for a given ticket ID, and the confirmation SHALL appear in stdout.

### Architectural Constraints

**Module: `platform.cli`** — CLI framework

```python
class CLI:
    """symphony CLI. Actions registered by workflows."""
    def __init__(self): ...
    def register_action(self, name: str, handler: Callable[[str, dict], None]): ...
    async def run(self, args: list[str]) -> None: ...

# Registered by SDD workflow:
#   symphony approve <ticket-id>
#   symphony reject <ticket-id> --reason "..."
#   symphony realign <ticket-id> --acs "..."
#   symphony unblock <ticket-id> [--note "..."]
#   symphony status [<ticket-id>]
```

**Decisions made** (from gap analysis):

- LangGraph's `interrupt()`/`Command(resume=...)` for human-in-the-loop. CLI sends resume commands to the graph.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

None specific to this slice.

## This Ticket's Acceptance Criteria

- [ ] `symphony approve <id>` merges feature branch to main, transitions to Done
- [ ] `symphony reject <id> --reason "..."` transitions back to Implementing with reason in contract
- [ ] `symphony realign <id> --acs "..."` records AC changelog entry (ADDED/MODIFIED/REMOVED), transitions to Implementing with new ACs
- [ ] `symphony unblock <id> [--note "..."]` resumes at blocked stage
- [ ] `symphony status [<id>]` shows current state for one or all tickets
- [ ] All actions appear in stdout with user, timestamp, reason
- [ ] All actions appear in ticket intervention history
- [ ] AC changelog entries include AC ID, change type (ADDED/MODIFIED/REMOVED), before/after, timestamp, actor

## Blocked by

- #05 Full pipeline