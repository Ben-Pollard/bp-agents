import logging
from datetime import datetime, timezone

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from bp_agents.workflows.sdd.state import (
    SDDFeatureState,
    TicketPipelineState,
)

logger = logging.getLogger(__name__)


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
    "ready": "implement",
    "implementing": "implement_complete",
    "awaiting_review": "review",
    "reviewing": "review",
    "awaiting_revision": "revise",
    "revising": "revise_complete",
    "awaiting_verification": "verify",
    "verifying": "verify",
    "awaiting_approval": "approve_final",
}


def route_ticket(state: TicketPipelineState) -> str:
    if state.get("blocked_reason") and state["status"] != "blocked":
        return "block"
    return ROUTE_MAP.get(state["status"], END)


def route_review(state: TicketPipelineState) -> str:
    if state.get("review_approved") is False:
        return "request_changes"
    return "approve_review"


def route_verify(state: TicketPipelineState) -> str:
    if state.get("verification_passed") is False:
        return "verification_fail"
    return "verification_pass"


def build_ticket_pipeline(
    checkpointer: SqliteSaver | None = None,
):
    builder = StateGraph(TicketPipelineState)

    builder.add_node("implement", _node("implementing"))
    builder.add_node("implement_complete", _node("awaiting_review"))
    builder.add_node("review", _node("reviewing"))
    builder.add_node("approve_review", _node("awaiting_verification"))
    builder.add_node("request_changes", _node("awaiting_revision"))
    builder.add_node("revise", _node("revising"))
    builder.add_node("revise_complete", _node("awaiting_verification"))
    builder.add_node("verify", _node("verifying"))
    builder.add_node("verification_pass", _node("awaiting_approval"))
    builder.add_node("verification_fail", _node("awaiting_revision"))
    builder.add_node("approve_final", _node("done"))
    builder.add_node("block", _node("blocked"))

    builder.add_conditional_edges(START, route_ticket)
    builder.add_conditional_edges("implement", route_ticket)
    builder.add_conditional_edges("implement_complete", route_ticket)
    builder.add_conditional_edges("review", route_review)
    builder.add_conditional_edges("approve_review", route_ticket)
    builder.add_conditional_edges("request_changes", route_ticket)
    builder.add_conditional_edges("revise", route_ticket)
    builder.add_conditional_edges("revise_complete", route_ticket)
    builder.add_conditional_edges("verify", route_verify)
    builder.add_conditional_edges("verification_pass", route_ticket)
    builder.add_conditional_edges("verification_fail", route_ticket)
    builder.add_conditional_edges("approve_final", route_ticket)
    builder.add_conditional_edges("block", route_ticket)

    return builder.compile(checkpointer=checkpointer)


def build_feature_pipeline(
    checkpointer: SqliteSaver | None = None,
):
    builder = StateGraph(SDDFeatureState)

    ticket_pipeline = build_ticket_pipeline(checkpointer=checkpointer)

    def process_tickets(state: SDDFeatureState) -> dict:
        updated_states: dict[str, TicketPipelineState] = {}
        for ticket in state["tickets"]:
            tid = ticket.id
            if tid not in state["ticket_states"]:
                ticket_state: TicketPipelineState = {
                    "ticket_id": tid,
                    "project": state["project"],
                    "status": "ready",
                    "tdd_output": None,
                    "review_output": None,
                    "revision_output": None,
                    "diff": None,
                    "review_approved": None,
                    "verification_passed": None,
                    "blocked_reason": None,
                }
            else:
                ticket_state = state["ticket_states"][tid]
            config = {"configurable": {"thread_id": tid}}
            result = ticket_pipeline.invoke(ticket_state, config)
            updated_states[tid] = result
        return {"ticket_states": updated_states}

    builder.add_node("process_tickets", process_tickets)
    builder.add_edge(START, "process_tickets")
    builder.add_edge("process_tickets", END)

    return builder.compile(checkpointer=checkpointer)
