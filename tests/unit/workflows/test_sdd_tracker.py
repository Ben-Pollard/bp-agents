import json

import httpx
import pytest

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState
from bp_agents.workflows.sdd.tracker import RedmineTracker
from tests.conftest import make_handler


def _populate_maps(tracker: RedmineTracker) -> None:
    tracker._status_map = {s.value: i + 1 for i, s in enumerate(TicketState)}
    tracker._reverse_map = {i + 1: s.value for i, s in enumerate(TicketState)}


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
            "status": {"id": 1, "name": "ready"},
            "subject": "Implement login",
            "description": "Add login flow",
            "created_on": "2024-01-01T00:00:00Z",
            "updated_on": "2024-01-01T00:00:00Z",
        }
    ]

    transport = httpx.MockTransport(
        make_handler(
            {"issues": mock_issues, "total_count": 1, "offset": 0, "limit": 25}
        )
    )
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )
    _populate_maps(tracker)

    results = await tracker.list_ready("project-1")

    assert len(results) == 1
    assert results[0]["id"] == "1"
    assert results[0]["name"] == "Implement login"


@pytest.mark.asyncio
async def test_update_state_calls_put() -> None:
    transport = httpx.MockTransport(make_handler({}))
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )
    _populate_maps(tracker)

    await tracker.update_state("1", "implementing", "project-1")


@pytest.mark.asyncio
async def test_get_item_returns_ticket() -> None:
    mock_issue = {
        "id": 1,
        "project": {"id": 1, "name": "project-1"},
        "tracker": {"id": 1, "name": "Bug"},
        "status": {"id": 1, "name": "ready"},
        "subject": "Implement login",
        "description": "Add login flow",
        "created_on": "2024-01-01T00:00:00Z",
        "updated_on": "2024-01-01T00:00:00Z",
    }

    transport = httpx.MockTransport(make_handler({"issue": mock_issue}))
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )
    _populate_maps(tracker)

    ticket = await tracker.get_item("1", "project-1")

    assert ticket["id"] == "1"
    assert ticket["name"] == "Implement login"


@pytest.mark.asyncio
async def test_ensure_statuses_uses_existing() -> None:
    existing_statuses = [
        {"id": 1, "name": "ready"},
        {"id": 2, "name": "implementing"},
        {"id": 3, "name": "awaiting_review"},
        {"id": 4, "name": "reviewing"},
        {"id": 5, "name": "awaiting_revision"},
        {"id": 6, "name": "revising"},
        {"id": 7, "name": "awaiting_verification"},
        {"id": 8, "name": "verifying"},
        {"id": 9, "name": "awaiting_approval"},
        {"id": 10, "name": "done"},
        {"id": 11, "name": "blocked"},
    ]
    handler_calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls.append({"method": request.method, "url": str(request.url)})
        return httpx.Response(
            status_code=200,
            json={"issue_statuses": existing_statuses},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )

    await tracker.ensure_statuses()

    assert len(handler_calls) == 1
    assert handler_calls[0]["method"] == "GET"
    assert tracker._status_map["ready"] == 1
    assert tracker._status_map["blocked"] == 11
    assert tracker._reverse_map[1] == "ready"
    assert tracker._reverse_map[11] == "blocked"


@pytest.mark.asyncio
async def test_ensure_statuses_creates_missing() -> None:
    existing_statuses = [
        {"id": 1, "name": "ready"},
        {"id": 2, "name": "done"},
    ]
    created_statuses: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                status_code=200,
                json={"issue_statuses": existing_statuses},
            )
        body = json.loads(request.content)
        created = body["issue_status"]
        new_id = 10 + len(created_statuses) + 1
        entry = {"id": new_id, **created}
        created_statuses.append(entry)
        return httpx.Response(
            status_code=201,
            json={"issue_status": entry},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://redmine:3000")
    tracker = RedmineTracker(
        base_url="http://redmine:3000",
        api_key="test-key",
        client=client,
    )

    await tracker.ensure_statuses()

    assert tracker._status_map["ready"] == 1
    assert tracker._status_map["done"] == 2
    for s in TicketState:
        assert s.value in tracker._status_map
