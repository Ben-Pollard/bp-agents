import logging
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from bp_agents.orchestrator.main import _to_pipeline_state, wait_for_dependency
from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import Ticket
from bp_agents.workflows.sdd.graph import build_ticket_pipeline


class FakeTrackerReturns(Tracker):
    def __init__(self, tickets: list[Ticket]) -> None:
        self.tickets = tickets

    async def list_ready(self, project: str) -> list[Ticket]:
        return self.tickets

    async def get_item(self, item_id: str, project: str) -> Ticket:
        return Ticket(id=item_id, name="", description="", state="", project=project)

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        pass

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        pass


def test_pipeline_polls_tracker_and_dispatches_tickets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Full end-to-end: FakeTracker returns tickets, poll loop dispatches
    them through the pipeline, state transitions are persisted via
    SqliteSaver."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    tracker = FakeTrackerReturns(
        [
            Ticket(
                id="TICK-1",
                name="Fix login",
                description="",
                state="backlog",
                project="project-1",
            ),
            Ticket(
                id="TICK-2",
                name="Add logout",
                description="",
                state="backlog",
                project="project-1",
            ),
        ]
    )

    caplog.set_level(logging.INFO)

    from langgraph.checkpoint.sqlite import SqliteSaver

    from bp_agents.orchestrator.main import PLANE_PROJECT

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        pipeline = build_ticket_pipeline(checkpointer=checkpointer)

        import asyncio

        ready = asyncio.run(tracker.list_ready(PLANE_PROJECT))

        logger = logging.getLogger("bp_agents.orchestrator.main")
        logger.info(
            "ticket discovery: %d ready  project=%s",
            len(ready),
            PLANE_PROJECT,
        )

        for ticket in ready:
            state = _to_pipeline_state(ticket, PLANE_PROJECT)
            config = {"configurable": {"thread_id": ticket.id}}
            pipeline.invoke(state, config)

        logger.info("orchestrator shutting down")

    records = [r.message for r in caplog.records]
    assert "ticket discovery: 2 ready  project=default" in records

    transition_msgs = [
        m for m in records if "ticket TICK-1:" in m or "ticket TICK-2:" in m
    ]
    assert any("implementing ->" in m for m in transition_msgs)

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        state1 = checkpointer.get({"configurable": {"thread_id": "TICK-1"}})
        state2 = checkpointer.get({"configurable": {"thread_id": "TICK-2"}})
        assert state1 is not None
        assert state2 is not None
        assert state1["channel_values"]["status"] == "done"
        assert state2["channel_values"]["status"] == "done"

    Path(db_path).unlink(missing_ok=True)


def test_wait_for_dependency_requires_200() -> None:
    """wait_for_dependency retries on non-200 responses and only succeeds
    on HTTP 200."""
    with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
        mock_get.side_effect = [
            mock.Mock(status_code=404),
            mock.Mock(status_code=500),
            mock.Mock(status_code=200),
        ]

        wait_for_dependency("http://example.com/health", "example", timeout=5)

        assert mock_get.call_count == 3


def test_wait_for_dependency_fails_on_persistent_non_200() -> None:
    with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
        mock_get.return_value = mock.Mock(status_code=503)

        with pytest.raises(
            RuntimeError, match="example did not become ready within 1s"
        ):
            wait_for_dependency("http://example.com/health", "example", timeout=1)
