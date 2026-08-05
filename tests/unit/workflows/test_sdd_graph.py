import pytest
from langgraph.graph import END

from bp_agents.workflows.sdd.contracts import Ticket, TicketState
from bp_agents.workflows.sdd.graph import (
    build_feature_pipeline,
    build_ticket_pipeline,
    route_review,
    route_ticket,
    route_verify,
)
from bp_agents.workflows.sdd.state import SDDFeatureState, TicketPipelineState


def test_build_ticket_pipeline_compiles() -> None:
    app = build_ticket_pipeline()
    assert app is not None


def _ts(
    status: str,
    review_approved: bool | None = None,
    verification_passed: bool | None = None,
    blocked_reason: str | None = None,
) -> TicketPipelineState:
    return {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "status": status,
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
        "review_approved": review_approved,
        "verification_passed": verification_passed,
        "blocked_reason": blocked_reason,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ready", "implement"),
        ("implementing", "implement_complete"),
        ("awaiting_review", "review"),
        ("awaiting_revision", "revise"),
        ("revising", "revise_complete"),
        ("awaiting_verification", "verify"),
        ("awaiting_approval", "approve_final"),
        ("done", END),
        ("blocked", END),
    ],
)
def test_route_ticket_returns_next_node(status: str, expected: str) -> None:
    assert route_ticket(_ts(status)) == expected


def test_route_review_returns_approve_by_default() -> None:
    assert route_review(_ts("reviewing")) == "approve_review"


def test_route_review_returns_request_changes_when_not_approved() -> None:
    assert route_review(_ts("reviewing", review_approved=False)) == "request_changes"


def test_route_verify_returns_pass_by_default() -> None:
    assert route_verify(_ts("verifying")) == "verification_pass"


def test_route_verify_returns_fail_when_not_passed() -> None:
    assert (
        route_verify(_ts("verifying", verification_passed=False)) == "verification_fail"
    )


def test_route_ticket_returns_block_when_blocked_reason() -> None:
    assert route_ticket(_ts("ready", blocked_reason="blocking issue")) == "block"


def test_route_ticket_returns_block_when_blocked_reason_and_implementing() -> None:
    assert route_ticket(_ts("implementing", blocked_reason="dep on API")) == "block"


def test_route_ticket_ignores_blocked_reason_when_already_blocked() -> None:
    assert route_ticket(_ts("blocked", blocked_reason="still blocked")) == END


def test_pipeline_advances_ready_to_completion() -> None:
    app = build_ticket_pipeline()
    initial = _ts("ready")
    result = app.invoke(initial, {"configurable": {"thread_id": "TICK-1"}})
    assert result["status"] == "done"


def test_pipeline_flow_from_awaiting_revision() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-3"}}
    initial = _ts("awaiting_revision")
    result = app.invoke(initial, config)
    assert result["status"] == "done"


def test_pipeline_flow_from_awaiting_verification() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-4"}}
    initial = _ts("awaiting_verification")
    result = app.invoke(initial, config)
    assert result["status"] == "done"


def test_build_feature_pipeline_compiles() -> None:
    app = build_feature_pipeline()
    assert app is not None


@pytest.mark.asyncio
async def test_feature_pipeline_processes_tickets() -> None:
    app = build_feature_pipeline()
    ticket = Ticket(
        id="TICK-1",
        name="test",
        description=None,
        state=TicketState.READY,
        project="project-1",
    )
    initial: SDDFeatureState = {
        "feature_id": "feat-1",
        "project": "project-1",
        "branch_name": None,
        "acs": [],
        "tickets": [ticket],
        "ticket_states": {},
        "current_stage": None,
        "blocked_reason": None,
    }
    config = {"configurable": {"thread_id": "feat-1"}}
    result = await app.ainvoke(initial, config)
    assert result["ticket_states"]["TICK-1"]["status"] == "done"
