from enum import StrEnum
from typing import Literal, TypedDict


class TicketState(StrEnum):
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
    TDD = "tdd"
    CODE_REVIEW = "code_review"
    REVISION = "revision"
    MINIMIZING_CODE = "minimizing_code"
    BEHAVIORAL_VERIFY = "behavioral_verify"
    DETERMINISTIC_GATE = "deterministic_gate"
    AWAIT_APPROVAL = "await_approval"
    MERGE = "merge"


class InterventionType(StrEnum):
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
    acs: list[dict]


class TddOutput(TypedDict):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    test_results: dict
    concerns: list[str]


class ReviewOutput(TypedDict):
    spec_compliance: bool
    code_quality: dict[str, bool]
    test_quality: dict[str, bool]
    operational: bool
    violations: list[dict]
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
    ac_results: list[dict]
    test_results: dict
