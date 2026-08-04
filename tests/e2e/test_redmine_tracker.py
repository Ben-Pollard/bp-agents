import httpx
import pytest

from bp_agents.workflows.sdd.tracker import RedmineTracker

pytestmark = pytest.mark.e2e


def _redmine_available() -> bool:
    try:
        r = httpx.get("http://localhost:8082/", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _redmine_available(), reason="Redmine not running")
@pytest.mark.asyncio
async def test_redmine_tracker_e2e_list_ready() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    assert isinstance(tickets, list)


@pytest.mark.skipif(not _redmine_available(), reason="Redmine not running")
@pytest.mark.asyncio
async def test_redmine_tracker_e2e_update_state() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    if tickets:
        await tracker.update_state(tickets[0].id, "implementing", "default")


@pytest.mark.skipif(not _redmine_available(), reason="Redmine not running")
@pytest.mark.asyncio
async def test_redmine_tracker_e2e_get_item() -> None:
    tracker = RedmineTracker(
        base_url="http://localhost:8082",
        api_key="",
        client=httpx.AsyncClient(base_url="http://localhost:8082"),
    )
    tickets = await tracker.list_ready("default")
    if tickets:
        ticket = await tracker.get_item(tickets[0].id, "default")
        assert ticket.id == tickets[0].id
