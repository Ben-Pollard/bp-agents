from langgraph.graph import END

from bp_agents.workflows.sdd.graph import (
    build_ticket_pipeline,
    route_ticket,
)
from bp_agents.workflows.sdd.state import TicketPipelineState


def test_build_ticket_pipeline_compiles() -> None:
    app = build_ticket_pipeline()
    assert app is not None


def _ts(status: str) -> TicketPipelineState:
    return {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "status": status,
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
    }


def test_route_ticket_returns_next_node() -> None:
    assert route_ticket(_ts("implementing")) == "implement"
    assert route_ticket(_ts("awaiting_review")) == "review"
    assert route_ticket(_ts("awaiting_revision")) == "revise"
    assert route_ticket(_ts("revising")) == "resubmit"
    assert route_ticket(_ts("awaiting_verification")) == "verify"
    assert route_ticket(_ts("awaiting_approval")) == "approve_final"
    assert route_ticket(_ts("done")) == END
    assert route_ticket(_ts("blocked")) == END
