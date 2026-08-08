from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


@dataclass
class Ticket:
    id: str
    name: str
    description: str | None
    state: "TicketState"
    project: str
    labels: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


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


class TddOutput(BaseModel):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL"]
    summary: str
    test_results: dict
    concerns: list[str]


class ReviewOutput(BaseModel):
    spec_compliance: bool
    code_quality: dict[str, bool]
    test_quality: dict[str, bool]
    operational: bool
    violations: list[dict]
    review_notes: list[str]
    action: Literal["approved", "changes_requested"]


class RevisionOutput(BaseModel):
    status: Literal["DONE", "DONE_WITH_CONCERNS", "BLOCKED"]
    summary: str
    violations_addressed: list[dict]
    violations_pushed_back: list[dict]
    violations_unclear: list[dict]
    test_results: dict
    concerns: list[str]
