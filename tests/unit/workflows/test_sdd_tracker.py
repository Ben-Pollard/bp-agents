import httpx
import pytest

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.tracker import RedmineTracker


def _make_handler(json_data: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=json_data)

    return handler


def test_redmine_tracker_implements_tracker() -> None:
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
    )
    assert isinstance(tracker, Tracker)
    assert tracker.base_url == "http://redmine:3000"
    assert tracker.api_key == "test-key"


@pytest.mark.asyncio
async def test_list_ready_returns_issues() -> None:
    mock_issues = [
        {
            "id": 1,
            "project": {"id": 1, "name": "project-1"},
            "tracker": {"id": 1, "name": "Bug"},
            "status": {"id": 1, "name": "New"},
            "subject": "Implement login",
            "description": "Add login flow",
            "created_on": "2024-01-01T00:00:00Z",
            "updated_on": "2024-01-01T00:00:00Z",
        }
    ]

    transport = httpx.MockTransport(
        _make_handler(
            {"issues": mock_issues, "total_count": 1, "offset": 0, "limit": 25}
        )
    )
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )

    results = await tracker.list_ready("project-1")

    assert len(results) == 1
    assert results[0].id == "1"
    assert results[0].name == "Implement login"


@pytest.mark.asyncio
async def test_update_state_calls_put() -> None:
    transport = httpx.MockTransport(_make_handler({}))
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )

    await tracker.update_state("1", "implementing", "project-1")


@pytest.mark.asyncio
async def test_get_item_returns_ticket() -> None:
    mock_issue = {
        "id": 1,
        "project": {"id": 1, "name": "project-1"},
        "tracker": {"id": 1, "name": "Bug"},
        "status": {"id": 1, "name": "New"},
        "subject": "Implement login",
        "description": "Add login flow",
        "created_on": "2024-01-01T00:00:00Z",
        "updated_on": "2024-01-01T00:00:00Z",
    }

    transport = httpx.MockTransport(_make_handler({"issue": mock_issue}))
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )

    ticket = await tracker.get_item("1", "project-1")

    assert ticket.id == "1"
    assert ticket.name == "Implement login"
