from bp_agents.workflows.sdd.state import SDDFeatureState, TicketPipelineState


def test_ticket_pipeline_state_defaults() -> None:
    state: TicketPipelineState = {
        "ticket_id": "TICK-1",
        "status": "implementing",
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
    }
    assert state["ticket_id"] == "TICK-1"
    assert state["status"] == "implementing"
    assert state["tdd_output"] is None


def test_sdd_feature_state_minimal() -> None:
    state: SDDFeatureState = {
        "feature_id": "FEAT-1",
        "project": "project-1",
        "branch_name": "feat/login",
        "acs": [],
        "tickets": [],
        "ticket_states": {},
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
    assert state["feature_id"] == "FEAT-1"
    assert state["current_stage"] == "tdd"
    assert len(state["acs"]) == 0
