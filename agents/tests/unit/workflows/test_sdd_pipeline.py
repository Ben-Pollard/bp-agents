from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.checkpoint.sqlite import SqliteSaver

from bp_agents.workflows.sdd.graph import build_ticket_pipeline

if TYPE_CHECKING:
    from bp_agents.workflows.sdd.state import TicketPipelineState


def test_pipeline_with_sqlite_persistence() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            app = build_ticket_pipeline(checkpointer=checkpointer)

            initial: TicketPipelineState = {
                "ticket_id": "TICK-1",
                "project": "project-1",
                "ticket_body": "",
                "status": "awaiting_revision",
                "tdd_output": None,
                "review_output": None,
                "revision_output": None,
                "diff": None,
                "review_approved": None,
                "verification_passed": None,
                "blocked_reason": None,
            }

            config = {"configurable": {"thread_id": "TICK-1"}}
            result = app.invoke(initial, config)
            assert result["status"] == "blocked"

        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            app2 = build_ticket_pipeline(checkpointer=checkpointer)

            saved_state = checkpointer.get({"configurable": {"thread_id": "TICK-1"}})
            assert saved_state is not None
            assert saved_state["channel_values"]["status"] == "blocked"

            config = {"configurable": {"thread_id": "TICK-1"}}
            result2 = app2.invoke(None, config)
            assert result2["status"] == "blocked"
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_multiple_tickets_no_interference() -> None:
    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        app = build_ticket_pipeline(checkpointer=checkpointer)

        ticket1: TicketPipelineState = {
            "ticket_id": "TICK-1",
            "project": "project-1",
            "ticket_body": "",
            "status": "awaiting_revision",
            "tdd_output": None,
            "review_output": None,
            "revision_output": None,
            "diff": None,
            "review_approved": None,
            "verification_passed": None,
            "blocked_reason": None,
        }

        ticket2: TicketPipelineState = {
            "ticket_id": "TICK-2",
            "project": "project-1",
            "ticket_body": "",
            "status": "awaiting_revision",
            "tdd_output": None,
            "review_output": None,
            "revision_output": None,
            "diff": None,
            "review_approved": None,
            "verification_passed": None,
            "blocked_reason": None,
        }

        r1 = app.invoke(ticket1, {"configurable": {"thread_id": "TICK-1"}})
        r2 = app.invoke(ticket2, {"configurable": {"thread_id": "TICK-2"}})

        assert r1["ticket_id"] == "TICK-1"
        assert r2["ticket_id"] == "TICK-2"
        assert r1["status"] == "blocked"
        assert r2["status"] == "blocked"
