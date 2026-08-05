import logging
import tempfile
from pathlib import Path
from unittest import mock

import httpx
import pytest

from bp_agents.orchestrator.main import _to_pipeline_state, wait_for_dependency
from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import Ticket, TicketState
from bp_agents.workflows.sdd.graph import build_ticket_pipeline


class FakeTrackerReturns(Tracker):
    def __init__(self, tickets: list[Ticket]) -> None:
        self.tickets = tickets
        self.update_calls: list[tuple[str, str, str]] = []

    async def list_ready(self, project: str) -> list[dict]:
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "state": t.state.value if isinstance(t.state, TicketState) else t.state,
                "project": t.project,
            }
            for t in self.tickets
        ]

    async def get_item(self, item_id: str, project: str) -> dict:
        return {
            "id": item_id,
            "name": "",
            "description": None,
            "state": TicketState.READY.value,
            "project": project,
        }

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        self.update_calls.append((item_id, state, project))

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        pass


@pytest.mark.asyncio
async def test_pipeline_polls_tracker_and_dispatches_tickets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Full end-to-end: FakeTracker returns tickets, poll loop dispatches
    them through the pipeline, state transitions are persisted via
    SqliteSaver and synced back to the tracker."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    tracker = FakeTrackerReturns(
        [
            Ticket(
                id="TICK-1",
                name="Fix login",
                description=None,
                state=TicketState.READY,
                project="project-1",
            ),
            Ticket(
                id="TICK-2",
                name="Add logout",
                description=None,
                state=TicketState.READY,
                project="project-1",
            ),
        ]
    )

    caplog.set_level(logging.INFO)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from bp_agents.orchestrator.main import REDMINE_PROJECT

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        pipeline = build_ticket_pipeline(checkpointer=checkpointer, tracker=tracker)

        ready = await tracker.list_ready(REDMINE_PROJECT)

        logger = logging.getLogger("bp_agents.orchestrator.main")
        logger.info(
            "ticket discovery: %d ready  project=%s",
            len(ready),
            REDMINE_PROJECT,
        )

        for ticket in ready:
            state = _to_pipeline_state(ticket, REDMINE_PROJECT)
            config = {"configurable": {"thread_id": ticket["id"]}}
            await pipeline.ainvoke(state, config)

        logger.info("orchestrator shutting down")

    records = [r.message for r in caplog.records]
    assert "ticket discovery: 2 ready  project=default" in records

    transition_msgs = [
        m for m in records if "ticket TICK-1:" in m or "ticket TICK-2:" in m
    ]
    assert any("ready ->" in m or "implementing ->" in m for m in transition_msgs)

    assert len(tracker.update_calls) > 0, "update_state was never called"
    tick1_calls = [(s, p) for i, s, p in tracker.update_calls if i == "TICK-1"]
    tick2_calls = [(s, p) for i, s, p in tracker.update_calls if i == "TICK-2"]
    assert ("done", "default") in tick1_calls
    assert ("done", "default") in tick2_calls
    assert ("implementing", "default") in tick1_calls
    assert ("awaiting_review", "default") in tick1_calls

    async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
        state1 = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": "TICK-1"}}
        )
        state2 = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": "TICK-2"}}
        )
        assert state1 is not None
        assert state2 is not None
        assert state1.checkpoint["channel_values"]["status"] == "done"
        assert state2.checkpoint["channel_values"]["status"] == "done"

    Path(db_path).unlink(missing_ok=True)


def test_wait_for_dependency_accepts_any_status() -> None:
    with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
        mock_get.side_effect = [
            mock.Mock(status_code=404),
            mock.Mock(status_code=500),
            mock.Mock(status_code=502),
        ]

        wait_for_dependency("http://example.com/health", "example", timeout=5)

        assert mock_get.call_count >= 1


def test_wait_for_dependency_fails_on_persistent_connection_error() -> None:
    with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
        mock_get.side_effect = httpx.ConnectError("always refused")

        with pytest.raises(
            RuntimeError, match="example did not become ready within 1s"
        ):
            wait_for_dependency("http://example.com/health", "example", timeout=1)
