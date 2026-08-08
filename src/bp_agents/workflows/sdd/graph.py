import functools
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from bp_agents.workflows.sdd.nodes.tdd import TddNode
from bp_agents.workflows.sdd.state import (
    TicketPipelineState,
)

if TYPE_CHECKING:
    from bp_agents.platform.agent_client import OpenCodeClient
    from bp_agents.platform.sandbox import Sandbox, SandboxConfig
    from bp_agents.platform.tracker import Tracker

logger = logging.getLogger(__name__)

_STUB_NOT_CONFIGURED_REASON = (
    "BP_TARGET_REPO_PATH not configured — set it to a target project "
    "repository path and ensure BP_SANDBOX_IMAGE is built"
)


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


def _node(target: str, tracker: "Tracker | None" = None):
    if tracker is not None:

        @functools.wraps(lambda: None)
        async def node_fn(state: TicketPipelineState) -> dict:
            result = _advance(state, target)
            await tracker.update_state(
                state["ticket_id"], target, state.get("project", "unknown")
            )
            return result

    else:

        @functools.wraps(lambda: None)
        def node_fn(state: TicketPipelineState) -> dict:
            return _advance(state, target)

    node_fn.__name__ = f"node_{target}"
    return node_fn


def _stub_implement_node(tracker: "Tracker | None" = None):
    """Stub 'implement' node used when the TDD pipeline is not configured.

    Blocks the ticket instead of silently advancing it through the pipeline
    to 'done', which would create a false positive without any real agent
    work (QA finding).
    """

    if tracker is not None:

        @functools.wraps(lambda: None)
        async def node_fn(state: TicketPipelineState) -> dict:
            ticket_id = state["ticket_id"]
            project = state.get("project", "unknown")
            logger.info(
                "ticket %s: blocked, reason: %s",
                ticket_id,
                _STUB_NOT_CONFIGURED_REASON,
            )
            await tracker.update_state(ticket_id, "blocked", project)
            return {
                "blocked_reason": _STUB_NOT_CONFIGURED_REASON,
            }

    else:

        @functools.wraps(lambda: None)
        def node_fn(state: TicketPipelineState) -> dict:
            logger.info(
                "ticket %s: blocked, reason: %s",
                state["ticket_id"],
                _STUB_NOT_CONFIGURED_REASON,
            )
            return {
                "blocked_reason": _STUB_NOT_CONFIGURED_REASON,
            }

    node_fn.__name__ = "node_implement"
    return node_fn


ROUTE_MAP: dict[str, str] = {
    "ready": "implement",
    "awaiting_review": "review",
    "awaiting_revision": "revise",
    "revising": "revise_complete",
    "awaiting_verification": "verify",
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
    checkpointer: AsyncSqliteSaver | None = None,
    tracker: "Tracker | None" = None,
    sandbox: "Sandbox | None" = None,
    sandbox_config: "SandboxConfig | None" = None,
    target_repo_path: str | None = None,
    skills_path: str | None = None,
    open_code_client: "OpenCodeClient | None" = None,
    otel_port: int | None = None,
):
    builder = StateGraph(TicketPipelineState)

    use_tdd = (
        sandbox is not None
        and sandbox_config is not None
        and target_repo_path is not None
    )

    if use_tdd:
        implement_node: Any = TddNode(
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=target_repo_path,
            skills_path=skills_path or "",
            tracker=tracker,
            client=open_code_client,
            otel_port=otel_port,
        )
    else:
        implement_node = _stub_implement_node(tracker)
        logger.warning(
            "TDD pipeline not configured — sandbox is None. "
            "Set BP_TARGET_REPO_PATH, BP_SANDBOX_IMAGE, and BP_SKILLS_PATH "
            "to enable real agent dispatch. %s",
            _STUB_NOT_CONFIGURED_REASON,
        )

    builder.add_node("implement", implement_node)
    builder.add_node("review", _node("reviewing", tracker))
    builder.add_node("approve_review", _node("awaiting_verification", tracker))
    builder.add_node("request_changes", _node("awaiting_revision", tracker))
    builder.add_node("revise", _node("revising", tracker))
    builder.add_node("revise_complete", _node("awaiting_verification", tracker))
    builder.add_node("verify", _node("verifying", tracker))
    builder.add_node("verification_pass", _node("awaiting_approval", tracker))
    builder.add_node("verification_fail", _node("awaiting_revision", tracker))
    builder.add_node("approve_final", _node("done", tracker))
    builder.add_node("block", _node("blocked", tracker))

    builder.add_conditional_edges(START, route_ticket)
    builder.add_conditional_edges("implement", route_ticket)
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
