from typing import Literal, TypedDict

from bp_agents.workflows.sdd.contracts import (
    ReviewOutput,
    RevisionOutput,
    TddOutput,
    Ticket,
)


class SDDFeatureState(TypedDict):
    feature_id: str
    project: str
    branch_name: str | None
    acs: list[dict]
    tickets: list[Ticket]
    ticket_states: dict[str, "TicketPipelineState"]
    current_stage: str | None
    blocked_reason: str | None


class TicketPipelineState(TypedDict):
    ticket_id: str
    project: str
    status: Literal[
        "ready",
        "implementing",
        "awaiting_review",
        "reviewing",
        "awaiting_revision",
        "revising",
        "awaiting_verification",
        "verifying",
        "awaiting_approval",
        "done",
        "blocked",
    ]
    tdd_output: TddOutput | None
    review_output: ReviewOutput | None
    revision_output: RevisionOutput | None
    diff: str | None
    review_approved: bool | None
    verification_passed: bool | None
    blocked_reason: str | None
