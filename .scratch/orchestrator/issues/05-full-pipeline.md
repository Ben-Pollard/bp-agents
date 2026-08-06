Status: ready-for-agent

# 05 — Full pipeline: Review → Revision → Minimizing Code → Behavioral Verify → Deterministic Gate → Approval → Merge

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001, ADR-0004, ADR-0005
- Glossary: `CONTEXT.md`

## What to Build

Complete all pipeline stages after TDD. Implement code review, revision, minimizing-code, behavioral verification, and deterministic gate nodes as real agent dispatches using `dispatch()` and `SKILL_CONFIGS`. Carry-forward context threads through all stages (TDD summary → review diff → revision feedback → minimizing notes → behavioral AC results → deterministic gate). Approval gate holds at Awaiting Approval until human action; merge on approval.

Pipeline stages:
1. **TDD** — already in #04
2. **Code review** — dispatches review agent with branch diff, produces `ReviewOutput`
3. **Revision** — dispatches agent with review feedback, commits revision changes
4. **Minimizing code** — dispatches agent with minimizing-code skill, audits codebase for eliminable lines per three questions (stdlib already solved? library could solve? code unnecessary?), produces `MinimizingOutput`
5. **Behavioral verify** — dispatches agent with playwright MCP enabled (browser), runs QA behavioral verification against acceptance criteria, produces `BehavioralVerifyOutput` with per-AC pass/fail and evidence
6. **Deterministic gate** — dispatches agent to run lint, typecheck, and test suite, exit pass/fail
7. **Await approval** — human reviews, approves
8. **Merge** — orchestrator merges feature branch to main

Complete Ready→Done path: TDD → code review → revision → minimizing code → behavioral verify → deterministic gate → Awaiting Approval → merge → Done → teardown.

## Requirements

### User Stories

- As a **developer**, I want to approve or reject completed work through the orchestrator, so merges to main are auditable system events.
- As a **developer**, I want to see every stage of a ticket's progress — what's running, what completed, what failed — so I can monitor the system at a glance.
- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.

### Domain Context

**Pipeline** (from reqs doc) — stages 2–4 (original) plus minimizing, behavioral verify, deterministic gate:

2. **Code review** — Orchestrator dispatches agent with the branch diff. Agent reviews the diff, produces feedback.
3. **Revision** — Orchestrator dispatches agent with feedback. Agent edits files to address feedback, exits with status and summary. Orchestrator commits revision changes.
4. **Verification** — Orchestrator dispatches agent. Agent runs tests in the workspace independently, exits with pass/fail.

The orchestrator passes carry-forward context between stages: TDD output includes summary → code review sees diff → revision sees feedback → minimizing code audits → behavioral verify confirms ACs → deterministic gate confirms deterministic checks pass. The agent never touches git.

**Approval and Code Delivery** (from reqs doc):

Agent-written code stays local until approval. The orchestrator maintains a local clone. The agent's feature branch is visible in the developer's git client for review. On approval, the orchestrator merges to main locally. Pushing to a remote is optional and post-approval. The orchestrator is the sole process that can merge to main.

### Behavioral Scenarios

**Scenario: Normal end-to-end (auto-complete, human approves)**

1. A ticket exists in Ready state: "Write a function that returns 'hello world' and a test."
2. Orchestrator poll finds the ticket, creates feature branch `feat/hello-1` from main, dispatches TDD agent with input contract (skill: tdd, ticket body).
3. TDD agent writes code and tests to the workspace, runs tests, exits with output contract `{status: complete, summary: "..."}`.
4. Orchestrator commits the agent's changes to `feat/hello-1`, transitions to Awaiting review.
5. Orchestrator dispatches code review agent with input contract (skill: requesting-code-review, diff of `main..feat/hello-1`, summary).
6. Code review agent reviews the diff, exits with `{status: complete, feedback: null}` (no issues).
7. Orchestrator transitions through revision (skipped — no feedback), minimizing code, behavioral verify, deterministic gate.
8. Behavioral verify agent runs QA skill with playwright MCP/browser against acceptance criteria, exits with per-AC pass/fail and evidence.
9. Deterministic gate agent runs lint, typecheck, and test suite, exits pass/fail.
10. Orchestrator transitions to Awaiting approval. Developer's git client shows `feat/hello-1` branch.
11. Developer reviews diff, runs `symphony approve hello-1`.
12. Orchestrator merges `feat/hello-1` to main, transitions to Done, tears down workspace.

**Scenario: Review finds issues, agent revises**

1. TDD completes, orchestrator commits changes, dispatches code review agent.
2. Code review agent exits with `{status: complete, feedback: "Edge case missing in test for empty input"}`.
3. Orchestrator transitions to Awaiting revision, dispatches revision agent with feedback in contract.
4. Revision agent edits files to add the missing test case, exits with `{status: complete, summary: "..."}`.
5. Orchestrator commits revision changes, transitions to minimizing code. Pipeline continues through all remaining stages.

### Acceptance Criteria

- [AC-03] WHEN a code review agent returns an output contract containing feedback, stdout SHALL log `ticket <id>: reviewing -> awaiting-revision` with the feedback, the feedback SHALL appear in the ticket's history in the front end, and the sandbox orchestration layer SHALL report a new session for the revision agent.
- [AC-04] WHEN a revision agent returns `status: complete`, stdout SHALL log `ticket <id>: revising -> awaiting-verification`, `git log` on the feature branch SHALL show the orchestrator's commit of revision changes, and the sandbox orchestration layer SHALL report a new session for the verification agent.
- [AC-05] WHEN a verification agent returns an output contract with `tests_pass: true`, stdout SHALL log `ticket <id>: verifying -> awaiting-approval`, the ticket SHALL appear in the Awaiting approval state in the front end and CLI, and the sandbox orchestration layer SHALL report no new sessions for that ticket.
- [AC-06] WHEN a human approves a ticket via CLI or the action surface, stdout SHALL log `ticket <id>: approved by <user>` and `git log` on main SHALL show the feature branch's commits merged.
- [AC-07] WHEN a ticket reaches Done, stdout SHALL log `ticket <id>: done, tearing down` and the sandbox orchestration layer SHALL report the ticket's sessions as torn down.
- [AC-16] The carry-forward context from stage N's output contract SHALL appear in stage N+1's input contract, visible when the ticket's contract history is queried in the front end.
- [AC-24] WHEN a human approves a ticket, `git log` on main SHALL show the merged commits — the merge was performed by the orchestrator, not by any agent.
- [AC-27] WHEN a ticket changes state, stdout SHALL log the transition (`ticket <id>: <from-state> -> <to-state>`) with a timestamp and the transition SHALL appear in the ticket's state history in the front end.
- [AC-39] WHILE a ticket is in any state other than Done, `git log` on any remote SHALL NOT show the feature branch's commits.
- [AC-40] WHEN a ticket reaches Awaiting approval, the feature branch SHALL appear in `git branch` output in the local repository and the branch name SHALL be visible in the ticket's status in the front end.

### Architectural Constraints

**Module: `workflows.sdd.skill_configs`** — declarative skill → config mapping (all stages):

```python
SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True, "task": False, "webfetch": False},
        mcps={},
    ),
    "code_review": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "deny"}},
        tools={"bash": True, "read": True, "edit": False, "task": False, "webfetch": False},
        mcps={},
    ),
    "revision": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}, "edit": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True, "task": False, "webfetch": False},
        mcps={},
    ),
    "minimizing_code": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "edit": {"*": "deny"}},
        tools={"bash": True, "read": True, "edit": False, "task": False, "webfetch": False},
        mcps={},
    ),
    "behavioral_verify": AgentConfig(
        model="openrouter/anthropic/claude-sonnet-4",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "task": False, "webfetch": False},
        mcps={"playwright": True},
    ),
    "deterministic_gate": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": False, "task": False},
        mcps={},
    ),
}
```

**Module: `workflows.sdd.contracts`** — SDD-specific types and stage contracts:

```python
from enum import StrEnum
from datetime import datetime
from typing import TypedDict, Literal, NotRequired

class TicketState(StrEnum):
    """SDD pipeline ticket lifecycle states."""
    READY = "ready"
    IMPLEMENTING = "implementing"
    AWAITING_REVIEW = "awaiting_review"
    REVIEWING = "reviewing"
    AWAITING_REVISION = "awaiting_revision"
    REVISING = "revising"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    DONE = "done"

class StageName(StrEnum):
    """SDD pipeline skill stages."""
    TDD = "tdd"
    CODE_REVIEW = "code_review"
    REVISION = "revision"
    MINIMIZING_CODE = "minimizing_code"
    BEHAVIORAL_VERIFY = "behavioral_verify"
    DETERMINISTIC_GATE = "deterministic_gate"
    AWAIT_APPROVAL = "await_approval"
    MERGE = "merge"

class InterventionType(StrEnum):
    """SDD workflow human intervention actions."""
    APPROVE = "approve"
    REJECT = "reject"
    REALIGN = "realign"
    UNBLOCK = "unblock"

class ACChange(TypedDict):
    timestamp: str
    actor: str
    ac_id: str
    change: Literal["ADDED", "MODIFIED", "REMOVED"]
    before: str | None
    after: str | None

class Intervention(TypedDict):
    timestamp: str
    actor: str
    type: InterventionType
    reason: str | None

class TicketSpec(TypedDict):
    ticket_id: str
    name: str
    description: str
    acs: list[dict]              # [{"id": "AC-01", "text": "..."}]

class TddOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    test_results: dict           # {"passed": N, "failed": N, "skipped": N}
    concerns: list[str]

class ReviewOutput(TypedDict):
    spec_compliance: bool
    code_quality: dict[str, bool]
    test_quality: dict[str, bool]
    operational: bool
    violations: list[dict]       # [{"principle": "...", "file": "...", "issue": "..."}]
    review_notes: list[str]
    action: Literal["approved", "changes_requested"]

class RevisionOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    violations_addressed: list[dict]
    violations_pushed_back: list[dict]
    violations_unclear: list[dict]
    test_results: dict
    concerns: list[str]

class MinimizingOutput(TypedDict):
    modules_audited: int
    total_lines: int
    lines_eliminable: int
    reduction_table: list[dict]
    violations: list[dict]
    review_notes: str
    action: Literal["approved", "changes_requested", "escalate"]

class BehavioralVerifyOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    ac_results: list[dict]       # [{"id": "AC-01", "pass": bool, "evidence": "..."}]
    test_results: dict
```

**Module: `workflows.sdd.graph`** — pipeline state:

```python
class SDDFeatureState(TypedDict):
    feature_id: str
    project: str
    branch_name: str
    acs: list[dict]
    tickets: list[TicketSpec]
    ticket_states: dict[str, TicketPipelineState]
    current_stage: StageName
    blocked_reason: str | None
    blocked_at_stage: StageName | None
    minimizing_output: MinimizingOutput | None
    behavioral_verify_output: BehavioralVerifyOutput | None
    deterministic_gate_passed: bool | None
    contracts: list[StageContract]
    ac_changelog: list[ACChange]
    interventions: list[Intervention]
```

**Decisions made** (from gap analysis):

- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- The orchestrator is the sole process that can merge to main.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.
- MCP dependencies baked into the sandbox image at build time. Per-dispatch opencode.json toggles `enabled: true/false` per skill. A single general-purpose sandbox image serves all skills.
- `SKILL_CONFIGS` declarative dict in `workflows.sdd.skill_configs` maps skill name → `AgentConfig(model, provider, permissions, tools, mcps)`. Workflow nodes declare intent; platform's `dispatch()` realizes it.

**ADR-0005**: No long-lived credentials in agent sandbox — LLM API keys injected via `PUT /auth/:id`. Credentials exist only in the opencode server process for the duration of the sandbox session.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- The orchestrator is the sole process that can merge to main.
- The system's README and startup experience must be sufficient for an agent (with a browser) to verify the system is working end-to-end without implementing workarounds or guessing at configuration.

## This Ticket's Acceptance Criteria

- [ ] Code review node dispatches review agent with branch diff, processes `ReviewOutput`
- [ ] Revision node dispatches agent with review feedback, commits revision changes
- [ ] Minimizing code node dispatches agent with minimizing-code skill, processes `MinimizingOutput`
- [ ] Behavioral verify node dispatches agent with playwright MCP enabled (browser), verifies ACs end-to-end through the browser, produces `BehavioralVerifyOutput` with per-AC pass/fail and evidence
- [ ] Deterministic gate node dispatches agent to run lint, typecheck, and test suite, exit pass/fail
- [ ] Carry-forward context flows from each stage output to next stage input
- [ ] Ticket reaches Awaiting Approval, feature branch visible in `git branch` and front-end
- [ ] Approve action merges feature branch to main
- [ ] Done state tears down workspace
- [ ] Feature branch not pushed to remote before approval
- [ ] No feedback from review (action: approved) skips revision and proceeds to minimizing code
- [ ] No changes requested from minimizing code proceeds to behavioral verify
- [ ] Stage-specific output types validated before transitioning
- [ ] Each stage uses correct `SKILL_CONFIGS` entry via `dispatch()`

## Blocked by

- #04 Agent client, Dispatch, Agent config, Skills mount, TDD stage