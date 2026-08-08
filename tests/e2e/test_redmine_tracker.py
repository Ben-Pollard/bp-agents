import httpx
import pytest

from bp_agents.workflows.sdd.tracker import RedmineTracker

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("redmine_compose"),
]


@pytest.mark.asyncio
async def test_redmine_tracker_e2e_list_ready() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    assert isinstance(tickets, list)


@pytest.mark.asyncio
async def test_redmine_tracker_e2e_update_state() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    if tickets:
        await tracker.update_state(tickets[0]["id"], "implementing", "default")


@pytest.mark.asyncio
async def test_redmine_tracker_e2e_get_item() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    if tickets:
        ticket = await tracker.get_item(tickets[0]["id"], "default")
        assert ticket["id"] == tickets[0]["id"]
