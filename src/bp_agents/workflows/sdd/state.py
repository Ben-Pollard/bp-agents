from typing import Literal, TypedDict

from bp_agents.workflows.sdd.contracts import (
    ReviewOutput,
    RevisionOutput,
    TddOutput,
)


class TicketPipelineState(TypedDict):
    ticket_id: str
    project: str
    status: Literal[
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
