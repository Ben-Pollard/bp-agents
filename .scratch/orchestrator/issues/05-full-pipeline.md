Status: ready-for-agent

# 05 — Full pipeline (Review → Revision → Verification → Approval)

## Source Documents

- Requirements: `docs/requirements/orchestrator-agent-contract.md`
- Architecture: `docs/architecture/gap-analysis.md`
- ADRs: ADR-0001
- Glossary: `CONTEXT.md`

## What to Build

Complete the remaining pipeline stages after TDD. Implement code review, revision, and verification nodes as real agent dispatches. Carry-forward context threads through all stages (TDD summary → review diff → revision feedback → verification confirms tests pass). Approval gate holds at Awaiting Approval until human action; merge stub present (actual merge via CLI in slice 6). Workspace persists across stages on single feature branch.

Complete Ready→Done path: TDD → code review → (optional revision) → verification → Awaiting Approval → merge → Done → teardown.

## Requirements

### User Stories

- As a **developer**, I want to approve or reject completed work through the orchestrator, so merges to main are auditable system events.
- As a **developer**, I want to see every stage of a ticket's progress — what's running, what completed, what failed — so I can monitor the system at a glance.
- As a **developer**, I want structured contracts between orchestrator and agent for each skill stage, so context is threaded predictably between stages.

### Domain Context

**Pipeline** (from reqs doc) — stages 2–4:

2. **Code review** — Orchestrator dispatches agent with the branch diff. Agent reviews the diff, produces feedback.
3. **Revision** — Orchestrator dispatches agent with feedback. Agent edits files to address feedback, exits with status and summary. Orchestrator commits revision changes.
4. **Verification** — Orchestrator dispatches agent. Agent runs tests in the workspace independently, exits with pass/fail.

The orchestrator passes carry-forward context between stages: TDD output includes summary → code review sees diff → revision sees feedback → verification confirms tests pass. The agent never touches git.

**Approval and Code Delivery** (from reqs doc):

Agent-written code stays local until approval. The orchestrator maintains a local clone. The agent's feature branch is visible in the developer's git client for review. On approval, the orchestrator merges to main locally. Pushing to a remote is optional and post-approval. The orchestrator is the sole process that can merge to main.

### Behavioral Scenarios

**Scenario: Normal end-to-end (auto-complete, human approves)**

(Full scenario from TDD through Done)

1. A ticket exists in Ready state: "Write a function that returns 'hello world' and a test."
2. Orchestrator poll finds the ticket, creates feature branch `feat/hello-1` from main, dispatches TDD agent with input contract (skill: tdd, ticket body).
3. TDD agent writes code and tests to the workspace, runs tests, exits with output contract `{status: complete, summary: "..."}`.
4. Orchestrator commits the agent's changes to `feat/hello-1`, transitions to Awaiting review.
5. Orchestrator dispatches code review agent with input contract (skill: requesting-code-review, diff of `main..feat/hello-1`, summary).
6. Code review agent reviews the diff, exits with `{status: complete, feedback: null}` (no issues).
7. Orchestrator transitions to Awaiting revision, then to Awaiting verification.
8. Orchestrator dispatches verification agent with input contract (skill: verification-before-completion, workspace at `feat/hello-1`).
9. Verification agent runs test suite independently, exits with `{status: complete, tests_pass: true}`.
10. Orchestrator transitions to Awaiting approval. Developer's git client shows `feat/hello-1` branch.
11. Developer reviews diff, runs `symphony approve hello-1`.
12. Orchestrator merges `feat/hello-1` to main, transitions to Done, tears down workspace.

**Scenario: Review finds issues, agent revises**

1. TDD completes, orchestrator commits changes, dispatches code review agent.
2. Code review agent exits with `{status: complete, feedback: "Edge case missing in test for empty input"}`.
3. Orchestrator transitions to Awaiting revision, dispatches revision agent with feedback in contract.
4. Revision agent edits files to add the missing test case, exits with `{status: complete, summary: "..."}`.
5. Orchestrator commits revision changes, transitions to Awaiting verification. Verification dispatched.
6. Verification exits with `{status: complete, tests_pass: true}`. Pipeline continues to Awaiting approval.

### Acceptance Criteria

- [AC-03] WHEN a code review agent returns an output contract containing feedback, stdout SHALL log `ticket <id>: reviewing -> awaiting-revision` with the feedback, the feedback SHALL appear in the ticket's history in the front end, and the sandbox orchestration layer SHALL report a new session for the revision agent.
- [AC-04] WHEN a revision agent returns `status: complete`, stdout SHALL log `ticket <id>: revising -> awaiting-verification`, `git log` on the feature branch SHALL show the orchestrator's commit of revision changes, and the sandbox orchestration layer SHALL report a new session for the verification agent.
- [AC-05] WHEN a verification agent returns an output contract with `tests_pass: true`, stdout SHALL log `ticket <id>: verifying -> awaiting-approval`, the ticket SHALL appear in the Awaiting approval state in the front end and CLI, and the sandbox orchestration layer SHALL report no new sessions for that ticket.
- [AC-06] WHEN a human approves a ticket via CLI or the action surface, stdout SHALL log `ticket <id>: approved by <user>` and `git log` on main SHALL show the feature branch's commits merged.
- [AC-07] WHEN a ticket reaches Done, stdout SHALL log `ticket <id>: done, tearing down` and the sandbox orchestration layer SHALL report the ticket's sessions as torn down.
- [AC-16] The carry-forward context from stage N's output contract SHALL appear in stage N+1's input contract, visible when the ticket's contract history is queried in the front end.
- [AC-24] WHEN a human approves a ticket, `git log` on main SHALL show the merged commits — the merge was performed by the orchestrator, not by any agent.
- [AC-39] WHILE a ticket is in any state other than Done, `git log` on any remote SHALL NOT show the feature branch's commits.
- [AC-40] WHEN a ticket reaches Awaiting approval, the feature branch SHALL appear in `git branch` output in the local repository and the branch name SHALL be visible in the ticket's status in the front end.

### Architectural Constraints

**Decisions made** (from gap analysis):

- Feature-level nested graph: one LangGraph graph per feature, containing ticket subgraphs (TDD → review → revision).
- Node functions are idempotent: check for existing opencode session before creating, check for existing `outcome_path` before re-dispatching.
- The orchestrator is the sole process that can merge to main.
- Workspace is host-persistent, bind-mounted into ephemeral sandbox containers per dispatch. Orchestrator owns all git state.

### Testing Decisions

Test strategy (from gap analysis): Node tests (mocked deps) → pipeline tests (fake opencode) → E2E tests (real everything).

### Non-Functional Requirements

- The orchestrator is the sole process that can merge to main.

## This Ticket's Acceptance Criteria

- [ ] Code review node reads diff, dispatches review agent, processes `ReviewOutput`
- [ ] Revision node dispatches agent with review feedback, commits revision changes
- [ ] Verification node dispatches agent with test suite, reads pass/fail from `BehavioralVerifyOutput`
- [ ] Carry-forward context flows from each stage output to next stage input
- [ ] Ticket reaches Awaiting Approval, feature branch visible in `git branch` and front-end
- [ ] Approve action merges feature branch to main (stub — real CLI in #06)
- [ ] Done state tears down workspace
- [ ] Feature branch not pushed to remote before approval
- [ ] No feedback from review (null/approved) skips revision and goes directly to verification
- [ ] Stage-specific output types validated before transitioning

## Blocked by

- #04 Agent client + TDD stage
