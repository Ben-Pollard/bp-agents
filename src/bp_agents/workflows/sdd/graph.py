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
    project = state.get("project", "unknown")
    logger.info(
        "ticket %s: %s -> %s  project=%s  [%s]",
        state["ticket_id"],
        from_,
        to,
        project,
        datetime.now(timezone.utc).isoformat(),
    )


def _advance(state: TicketPipelineState, to: str) -> dict:
    _log(state, to)
    return {"status": to}


def _node(target: str):
    def node_fn(state: TicketPipelineState) -> dict:
        return _advance(state, target)

    return node_fn


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


def build_ticket_pipeline(
    checkpointer: SqliteSaver | None = None,
):
    builder = StateGraph(TicketPipelineState)

    builder.add_node("implement", _node(NEXT_STATE["implementing"]))
    builder.add_node("review", _node(NEXT_STATE["awaiting_review"]))
    builder.add_node("approve_review", _node("awaiting_verification"))
    builder.add_node("request_changes", _node("awaiting_revision"))
    builder.add_node("revise", _node(NEXT_STATE["awaiting_revision"]))
    builder.add_node("resubmit", _node(NEXT_STATE["revising"]))
    builder.add_node("verify", _node(NEXT_STATE["awaiting_verification"]))
    builder.add_node("verification_pass", _node("awaiting_approval"))
    builder.add_node("verification_fail", _node("awaiting_revision"))
    builder.add_node("approve_final", _node(NEXT_STATE["awaiting_approval"]))
    builder.add_node("handle_blocked", _node("blocked"))

    builder.add_conditional_edges(START, route_ticket)
    builder.add_conditional_edges(
        "review",
        lambda s: "approve_review",
        {
            "approve_review": "approve_review",
            "request_changes": "request_changes",
        },
    )
    builder.add_conditional_edges(
        "verify",
        lambda s: "verification_pass",
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
