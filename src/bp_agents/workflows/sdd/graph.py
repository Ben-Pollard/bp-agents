import json
import logging
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from bp_agents.workflows.sdd.contracts import QaOutput, ReviewOutput, TddOutput
from bp_agents.workflows.sdd.nodes.agent_stage import AgentStageNode
from bp_agents.workflows.sdd.state import (
    TicketPipelineState,
)

if TYPE_CHECKING:
    from bp_agents.platform.agent_client import OpenCodeClient
    from bp_agents.platform.mcp.contract_broker import ContractBroker
    from bp_agents.platform.sandbox import Sandbox, SandboxConfig
    from bp_agents.platform.tracker import Tracker

logger = logging.getLogger(__name__)

ROUTE_MAP: dict[str, str] = {
    "ready": "implement",
    "awaiting_review": "review",
    "awaiting_revision": "revise",
    "awaiting_verification": "verify",
}


def route_ticket(state: TicketPipelineState) -> str:
    if state.get("blocked_reason") and state["status"] != "blocked":
        return "block"
    return ROUTE_MAP.get(state["status"], END)


def build_ticket_pipeline(
    checkpointer: AsyncSqliteSaver | None = None,
    tracker: "Tracker | None" = None,
    sandbox: "Sandbox | None" = None,
    sandbox_config: "SandboxConfig | None" = None,
    target_repo_path: str | None = None,
    skills_path: str | None = None,
    open_code_client: "OpenCodeClient | None" = None,
    otel_port: int | None = None,
    broker: "ContractBroker | None" = None,
    mcp_port: int | None = None,
):
    builder = StateGraph(TicketPipelineState)

    use_stages = (
        sandbox is not None
        and sandbox_config is not None
        and target_repo_path is not None
    )

    base_kwargs: dict[str, Any] = {}
    if use_stages:
        base_kwargs = dict(
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=target_repo_path,
            skills_path=skills_path or "",
            tracker=tracker,
            client=open_code_client,
            otel_port=otel_port,
            broker=broker,
            mcp_port=mcp_port,
        )

    if use_stages:
        implement_node: Any = AgentStageNode(
            **base_kwargs,
            skill="tdd",
            contract_cls=TddOutput,
            stage_status="implementing",
            commit=True,
            route_result=lambda o, s: (
                {"status": "awaiting_review", "tdd_output": o}
                if o.status == "DONE"
                else {"blocked_reason": f"agent: {o.status}"}
            ),
        )
        review_node: Any = AgentStageNode(
            **base_kwargs,
            skill="requesting-code-review",
            contract_cls=ReviewOutput,
            stage_status="reviewing",
            commit=False,
            route_result=lambda o, s: (
                {
                    "status": "awaiting_verification",
                    "review_output": o,
                    "review_approved": True,
                }
                if o.action == "approved"
                else {
                    "status": "awaiting_revision",
                    "review_output": o,
                    "review_approved": False,
                }
            ),
        )
        revise_node: Any = AgentStageNode(
            **base_kwargs,
            skill="receiving-code-review",
            contract_cls=TddOutput,
            stage_status="revising",
            commit=True,
            extra_prompt=lambda s: (
                f"Review feedback:\n"
                f"{json.dumps(s.get('review_output', {}).model_dump() if s.get('review_output') else {}, indent=2)}"
                if s.get("review_output")
                else ""
            ),
            route_result=lambda o, s: (
                {"status": "awaiting_review", "tdd_output": o}
                if o.status == "DONE"
                else {"blocked_reason": f"agent: {o.status}"}
            ),
        )
        qa_node: Any = AgentStageNode(
            **base_kwargs,
            skill="qa",
            contract_cls=QaOutput,
            stage_status="verifying",
            commit=False,
            route_result=lambda o, s: (
                {
                    "status": "awaiting_approval",
                    "qa_output": o,
                    "verification_passed": True,
                }
                if o.status == "PASS"
                else {
                    "status": "awaiting_revision",
                    "qa_output": o,
                    "verification_passed": False,
                }
            ),
        )
    else:

        def _stub_block(state: TicketPipelineState) -> dict:
            logger.info(
                "ticket %s: blocked, reason: BP_TARGET_REPO_PATH not configured",
                state["ticket_id"],
            )
            return {"blocked_reason": "BP_TARGET_REPO_PATH not configured"}

        implement_node = _stub_block
        review_node = _stub_block
        revise_node = _stub_block
        qa_node = _stub_block

    builder.add_node("implement", implement_node)
    builder.add_node("review", review_node)
    builder.add_node("revise", revise_node)
    builder.add_node("verify", qa_node)
    builder.add_node("block", _node("blocked", tracker))

    builder.add_conditional_edges(START, route_ticket)
    for n in ("implement", "review", "revise", "verify", "block"):
        builder.add_conditional_edges(n, route_ticket)

    return builder.compile(checkpointer=checkpointer)


def _node(target: str, tracker: "Tracker | None" = None):
    import functools

    if tracker is not None:

        @functools.wraps(lambda: None)
        async def node_fn(state: TicketPipelineState) -> dict:
            await tracker.update_state(
                state["ticket_id"], target, state.get("project", "unknown")
            )
            return {"status": target}

    else:

        @functools.wraps(lambda: None)
        def node_fn(state: TicketPipelineState) -> dict:
            return {"status": target}

    node_fn.__name__ = f"node_{target}"
    return node_fn
