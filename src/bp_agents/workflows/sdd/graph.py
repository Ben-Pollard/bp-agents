import logging
from datetime import datetime, timezone

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from bp_agents.workflows.sdd.state import TicketPipelineState

logger = logging.getLogger(__name__)

NEXT_STATE: dict[str, str] = {
    "implementing": "awaiting_review",
    "awaiting_review": "reviewing",
    "reviewing": "__DECIDE_REVIEW__",
    "awaiting_revision": "revising",
    "revising": "awaiting_review",
    "awaiting_verification": "verifying",
    "verifying": "__DECIDE_VERIFICATION__",
    "awaiting_approval": "done",
    "done": "__END__",
    "blocked": "__END__",
}


def _log(state: TicketPipelineState, to: str) -> None:
    from_ = state["status"]
    logger.info(
        "ticket %s: %s -> %s  [%s]",
        state["ticket_id"],
        from_,
        to,
        datetime.now(timezone.utc).isoformat(),
    )


def _advance(state: TicketPipelineState, to: str) -> dict:
    _log(state, to)
    return {"status": to}


def implement(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_review")


def review(state: TicketPipelineState) -> dict:
    return _advance(state, "reviewing")


def approve_review(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_verification")


def request_changes(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_revision")


def revise(state: TicketPipelineState) -> dict:
    return _advance(state, "revising")


def resubmit(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_review")


def verify(state: TicketPipelineState) -> dict:
    return _advance(state, "verifying")


def verification_pass(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_approval")


def verification_fail(state: TicketPipelineState) -> dict:
    return _advance(state, "awaiting_revision")


def approve_final(state: TicketPipelineState) -> dict:
    return _advance(state, "done")


def handle_blocked(state: TicketPipelineState) -> dict:
    return _advance(state, "blocked")


ROUTE_MAP: dict[str, str] = {
    "implementing": "implement",
    "awaiting_review": "review",
    "awaiting_revision": "revise",
    "revising": "resubmit",
    "awaiting_verification": "verify",
    "awaiting_approval": "approve_final",
}


def route_ticket(state: TicketPipelineState) -> str:
    return ROUTE_MAP.get(state["status"], END)


def decide_review(state: TicketPipelineState) -> str:
    # Stub: always approve. Real implementation checks review_output.
    return "approve_review"


def decide_verification(state: TicketPipelineState) -> str:
    # Stub: always pass. Real implementation checks behavioral_verify_output.
    return "verification_pass"


def build_ticket_pipeline(
    checkpointer: SqliteSaver | None = None,
):
    builder = StateGraph(TicketPipelineState)

    builder.add_node("implement", implement)
    builder.add_node("review", review)
    builder.add_node("approve_review", approve_review)
    builder.add_node("request_changes", request_changes)
    builder.add_node("revise", revise)
    builder.add_node("resubmit", resubmit)
    builder.add_node("verify", verify)
    builder.add_node("verification_pass", verification_pass)
    builder.add_node("verification_fail", verification_fail)
    builder.add_node("approve_final", approve_final)
    builder.add_node("handle_blocked", handle_blocked)

    builder.add_conditional_edges(START, route_ticket)
    builder.add_conditional_edges(
        "review",
        decide_review,
        {
            "approve_review": "approve_review",
            "request_changes": "request_changes",
        },
    )
    builder.add_conditional_edges(
        "verify",
        decide_verification,
        {
            "verification_pass": "verification_pass",
            "verification_fail": "verification_fail",
        },
    )
    builder.add_conditional_edges("implement", route_ticket)
    builder.add_conditional_edges("approve_review", route_ticket)
    builder.add_conditional_edges("request_changes", route_ticket)
    builder.add_conditional_edges("revise", route_ticket)
    builder.add_conditional_edges("resubmit", route_ticket)
    builder.add_conditional_edges("verification_pass", route_ticket)
    builder.add_conditional_edges("verification_fail", route_ticket)
    builder.add_conditional_edges("approve_final", route_ticket)

    return builder.compile(checkpointer=checkpointer)


def advance_ticket(state: dict, ticket_id: str) -> dict:
    ts = state["ticket_states"][ticket_id]
    next_ = NEXT_STATE.get(ts["status"])
    if not next_ or next_ == "__END__":
        return state
    if next_ == "__DECIDE_REVIEW__":
        approved = bool(
            ts.get("review_output") and ts["review_output"].get("action") == "approved"
        )
        next_ = "awaiting_verification" if approved else "awaiting_revision"
    elif next_ == "__DECIDE_VERIFICATION__":
        passed = bool(
            ts.get("behavioral_verify_output")
            and ts["behavioral_verify_output"].get("status") == "DONE"
        )
        next_ = "awaiting_approval" if passed else "awaiting_revision"
    from_ = ts["status"]
    ts["status"] = next_
    logger.info(
        "ticket %s: %s -> %s  [%s]",
        ticket_id,
        from_,
        next_,
        datetime.now(timezone.utc).isoformat(),
    )
    state["ticket_states"][ticket_id] = ts
    return state
