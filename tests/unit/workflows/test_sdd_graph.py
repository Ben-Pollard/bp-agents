import logging

import pytest
from langgraph.graph import END

from bp_agents.workflows.sdd.graph import (
    advance_ticket,
    build_ticket_pipeline,
    route_ticket,
)
from bp_agents.workflows.sdd.state import SDDFeatureState, TicketPipelineState


@pytest.fixture
def feature_state() -> SDDFeatureState:
    return {
        "feature_id": "FEAT-1",
        "project": "project-1",
        "branch_name": "feat/login",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "implementing",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }


def test_build_ticket_pipeline_compiles() -> None:
    app = build_ticket_pipeline()
    assert app is not None


def _ts(status: str) -> TicketPipelineState:
    return {
        "ticket_id": "TICK-1",
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


def test_advance_ticket_transitions_implementing() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "implementing",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    result = advance_ticket(state, "TICK-1")
    assert result["ticket_states"]["TICK-1"]["status"] == "awaiting_review"


def test_advance_ticket_full_flow(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "implementing",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_review"

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "reviewing"

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_revision"

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "revising"

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_review"

    assert any("ticket TICK-1:" in msg for msg in caplog.messages)


def test_advance_ticket_review_with_approval() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "reviewing",
                "tdd_output": None,
                "review_output": {
                    "spec_compliance": True,
                    "code_quality": {"naming": True, "complexity": True},
                    "test_quality": {"coverage": True, "meaningful": True},
                    "operational": True,
                    "violations": [],
                    "review_notes": [],
                    "action": "approved",
                },
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_verification"


def test_advance_ticket_verification_fail() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "verifying",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_revision"


def test_advance_ticket_verification_pass() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "verifying",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
                "behavioral_verify_output": {
                    "status": "DONE",
                    "ac_results": [],
                    "test_results": {"passed": 5, "failed": 0, "skipped": 0},
                },
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "awaiting_approval"


def test_advance_ticket_to_done() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "p1",
        "branch_name": "b1",
        "acs": [],
        "tickets": [],
        "ticket_states": {
            "TICK-1": {
                "ticket_id": "TICK-1",
                "status": "awaiting_approval",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
            }
        },
        "current_stage": "tdd",
        "blocked_reason": None,
        "blocked_at_stage": None,
        "minimizing_output": None,
        "behavioral_verify_output": None,
        "deterministic_gate_passed": None,
        "contracts": [],
        "ac_changelog": [],
        "interventions": [],
    }

    advance_ticket(state, "TICK-1")
    assert state["ticket_states"]["TICK-1"]["status"] == "done"
