from typing import Literal, TypedDict

from bp_agents.platform.contracts import StageContract
from bp_agents.workflows.sdd.contracts import (
    ACChange,
    BehavioralVerifyOutput,
    Intervention,
    MinimizingOutput,
    ReviewOutput,
    RevisionOutput,
    StageName,
    TddOutput,
    TicketSpec,
)


class TicketPipelineState(TypedDict):
    ticket_id: str
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
