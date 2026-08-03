from datetime import datetime

import httpx
import pytest

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState
from bp_agents.workflows.sdd.tracker import PlaneTracker, Ticket


def _make_handler(json_data: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=json_data)

    return handler


def test_ticket_dataclass() -> None:
    ticket = Ticket(
        id="TICK-1",
        name="Add login",
        description="Implement login flow",
        state=TicketState.READY,
        project="project-1",
        labels=["feature"],
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 2),
    )
    assert ticket.id == "TICK-1"
    assert ticket.state == TicketState.READY
    assert ticket.project == "project-1"


def test_plane_tracker_implements_tracker() -> None:
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
    )
    assert isinstance(tracker, Tracker)
    assert tracker.base_url == "http://plane:80"
    assert tracker.api_key == "test-key"
    assert tracker.workspace_slug == "test-ws"


@pytest.mark.asyncio
async def test_list_ready_returns_issues() -> None:
    mock_results = [
        {
            "id": "issue-1",
            "name": "Implement login",
            "description": "Add login flow",
            "state": "ready",
            "project": "project-1",
        }
    ]

    transport = httpx.MockTransport(_make_handler({"results": mock_results}))
    client = httpx.AsyncClient(transport=transport, base_url="http://plane:80")
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
        client=client,
    )

    results = await tracker.list_ready("project-1")

    assert len(results) == 1
    assert results[0]["id"] == "issue-1"


@pytest.mark.asyncio
async def test_get_item_returns_none_on_404() -> None:
    transport = httpx.MockTransport(_make_handler({}, status_code=404))
    client = httpx.AsyncClient(transport=transport, base_url="http://plane:80")
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
        client=client,
    )

    result = await tracker.get_item("nonexistent", "project-1")
    assert result is None


@pytest.mark.asyncio
async def test_update_state_calls_patch() -> None:
    transport = httpx.MockTransport(_make_handler({}))
    client = httpx.AsyncClient(transport=transport, base_url="http://plane:80")
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
        client=client,
    )

    await tracker.update_state("issue-1", "implementing", "project-1")


@pytest.mark.asyncio
async def test_add_comment_calls_post() -> None:
    transport = httpx.MockTransport(_make_handler({}, status_code=201))
    client = httpx.AsyncClient(transport=transport, base_url="http://plane:80")
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
        client=client,
    )

    await tracker.add_comment("issue-1", "Starting implementation", "project-1")
