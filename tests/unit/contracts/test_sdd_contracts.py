from bp_agents.workflows.sdd.contracts import (
    ACChange,
    BehavioralVerifyOutput,
    Intervention,
    InterventionType,
    MinimizingOutput,
    ReviewOutput,
    RevisionOutput,
    StageName,
    TddOutput,
    TicketSpec,
    TicketState,
)


def test_ticket_state_values() -> None:
    assert TicketState.READY.value == "ready"
    assert TicketState.IMPLEMENTING.value == "implementing"
    assert TicketState.AWAITING_REVIEW.value == "awaiting_review"
    assert TicketState.REVIEWING.value == "reviewing"
    assert TicketState.AWAITING_REVISION.value == "awaiting_revision"
    assert TicketState.REVISING.value == "revising"
    assert TicketState.AWAITING_VERIFICATION.value == "awaiting_verification"
    assert TicketState.VERIFYING.value == "verifying"
    assert TicketState.AWAITING_APPROVAL.value == "awaiting_approval"
    assert TicketState.BLOCKED.value == "blocked"
    assert TicketState.DONE.value == "done"


def test_stage_name_values() -> None:
    assert StageName.TDD.value == "tdd"
    assert StageName.CODE_REVIEW.value == "code_review"
    assert StageName.REVISION.value == "revision"
    assert StageName.MINIMIZING_CODE.value == "minimizing_code"
    assert StageName.BEHAVIORAL_VERIFY.value == "behavioral_verify"
    assert StageName.DETERMINISTIC_GATE.value == "deterministic_gate"
    assert StageName.AWAIT_APPROVAL.value == "await_approval"
    assert StageName.MERGE.value == "merge"


def test_intervention_type_values() -> None:
    assert InterventionType.APPROVE.value == "approve"
    assert InterventionType.REJECT.value == "reject"
    assert InterventionType.REALIGN.value == "realign"
    assert InterventionType.UNBLOCK.value == "unblock"


def test_ac_change_typeddict() -> None:
    ac: ACChange = {
        "timestamp": "2025-01-01T00:00:00Z",
        "actor": "user1",
        "ac_id": "AC-01",
        "change": "ADDED",
        "before": None,
        "after": "System shall log events",
    }
    assert ac["ac_id"] == "AC-01"
    assert ac["change"] == "ADDED"


def test_intervention_typeddict() -> None:
    iv: Intervention = {
        "timestamp": "2025-01-01T00:00:00Z",
        "actor": "user1",
        "type": InterventionType.APPROVE,
        "reason": "LGTM",
    }
    assert iv["type"] == InterventionType.APPROVE
    assert iv["reason"] == "LGTM"


def test_ticket_spec_typeddict() -> None:
    spec: TicketSpec = {
        "ticket_id": "TICK-1",
        "name": "Add login",
        "description": "Implement login flow",
        "acs": [{"id": "AC-01", "text": "User can log in"}],
    }
    assert spec["ticket_id"] == "TICK-1"
    assert len(spec["acs"]) == 1


def test_tdd_output_typeddict() -> None:
    out: TddOutput = {
        "status": "DONE",
        "summary": "All tests pass",
        "test_results": {"passed": 5, "failed": 0, "skipped": 0},
        "concerns": [],
    }
    assert out["status"] == "DONE"


def test_review_output_typeddict() -> None:
    out: ReviewOutput = {
        "spec_compliance": True,
        "code_quality": {"naming": True, "complexity": False},
        "test_quality": {"coverage": True, "meaningful": True},
        "operational": True,
        "violations": [{"principle": "DRY", "file": "main.py", "issue": "Duplication"}],
        "review_notes": ["Refactor loop"],
        "action": "changes_requested",
    }
    assert out["action"] == "changes_requested"
    assert len(out["violations"]) == 1


def test_revision_output_typeddict() -> None:
    out: RevisionOutput = {
        "status": "DONE",
        "summary": "Addressed all issues",
        "violations_addressed": [],
        "violations_pushed_back": [],
        "violations_unclear": [],
        "test_results": {"passed": 5, "failed": 0, "skipped": 0},
        "concerns": [],
    }
    assert out["status"] == "DONE"


def test_minimizing_output_typeddict() -> None:
    out: MinimizingOutput = {
        "modules_audited": 3,
        "total_lines": 150,
        "lines_eliminable": 20,
        "reduction_table": [{"module": "main.py", "before": 50, "after": 30}],
        "violations": [],
        "review_notes": "Good structure",
        "action": "approved",
    }
    assert out["modules_audited"] == 3
    assert out["action"] == "approved"


def test_behavioral_verify_output_typeddict() -> None:
    out: BehavioralVerifyOutput = {
        "status": "DONE",
        "ac_results": [{"id": "AC-01", "pass": True, "evidence": "Test passes"}],
        "test_results": {"passed": 10, "failed": 0, "skipped": 0},
    }
    assert out["status"] == "DONE"
    assert out["ac_results"][0]["pass"] is True
