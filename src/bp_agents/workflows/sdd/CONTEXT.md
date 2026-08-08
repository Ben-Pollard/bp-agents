# SDD Workflow

A ticket-driven autonomous software development agent. Discovers tickets from a tracker, dispatches coding agents through a pipeline of skill stages, and merges approved work to main.

## Language

**Ticket**:
A unit of work tracked in Redmine, with ID, body, and state. The orchestrator discovers ready tickets via the tracker and drives them through the pipeline.
_Avoid_: Issue, task, card

**Feature**:
A collection of related tickets. The unit of verification and approval.
_Avoid_: Epic, story

**Tracker** (Redmine adapter):
The Redmine API adapter that discovers ready tickets and updates their state. Implements the platform's tracker port.
_Avoid_: Backend, store, database

**TicketState**:
The SDD pipeline's ticket lifecycle states: ready, implementing, awaiting_review, reviewing, awaiting_revision, revising, awaiting_verification, verifying, awaiting_approval, blocked, done.
_Avoid_: Status, phase

**StageName** (SDD):
The SDD pipeline's skill stages: tdd, code_review, revision, minimizing_code, behavioral_verify, deterministic_gate, await_approval, merge.

**Intervention**:
A human action on a ticket: approve, reject, realign, or unblock. Recorded with actor, timestamp, and reason.
_Avoid_: Action, command, operation