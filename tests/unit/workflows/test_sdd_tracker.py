from datetime import datetime
from unittest import mock

import httpx
import pytest

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState
from bp_agents.workflows.sdd.tracker import PlaneTracker, Ticket


def _async_resp(
    status_code: int = 200, json_data: dict | None = None
) -> mock.AsyncMock:
    resp = mock.AsyncMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = mock.AsyncMock(return_value=json_data or {})
    return resp


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
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
    )
    mock_results = [
        {
            "id": "issue-1",
            "name": "Implement login",
            "description": "Add login flow",
            "state": "ready",
            "project": "project-1",
        }
    ]

    with mock.patch.object(tracker._client, "get") as mock_get:
        mock_get.return_value = _async_resp(json_data={"results": mock_results})

        results = await tracker.list_ready("project-1")

        assert len(results) == 1
        assert results[0]["id"] == "issue-1"
        mock_get.assert_called_once_with(
            "/api/v1/workspaces/test-ws/projects/project-1/issues",
            params={"state_group": "backlog"},
        )


@pytest.mark.asyncio
async def test_get_item_returns_none_on_404() -> None:
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
    )

    with mock.patch.object(tracker._client, "get") as mock_get:
        mock_get.return_value = _async_resp(status_code=404)

        result = await tracker.get_item("nonexistent")
        assert result is None


@pytest.mark.asyncio
async def test_update_state_calls_patch() -> None:
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
    )

    with mock.patch.object(tracker._client, "patch") as mock_patch:
        mock_patch.return_value = _async_resp()

        await tracker.update_state("issue-1", "implementing")

        mock_patch.assert_called_once_with(
            "/api/v1/workspaces/test-ws/projects/__all__/issues/issue-1",
            json={"state": "implementing"},
        )


@pytest.mark.asyncio
async def test_add_comment_calls_post() -> None:
    tracker = PlaneTracker(
        base_url="http://plane:80",
        api_key="test-key",
        workspace_slug="test-ws",
    )

    with mock.patch.object(tracker._client, "post") as mock_post:
        mock_post.return_value = _async_resp(status_code=201)

        await tracker.add_comment("issue-1", "Starting implementation")

        mock_post.assert_called_once_with(
            "/api/v1/workspaces/test-ws/projects/__all__/issues/issue-1/comments",
            json={"body": "Starting implementation"},
        )
