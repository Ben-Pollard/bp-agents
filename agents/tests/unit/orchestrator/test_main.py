import asyncio
from unittest import mock

import httpx
import pytest

from bp_agents.platform.runner import wait_for_dependency
from bp_agents.platform.tracker import Tracker
from bp_agents.platform.work_initiator import TrackerPoller


class FakeTracker(Tracker):
    def __init__(self, tickets: list[dict] | None = None) -> None:
        self.tickets = tickets or []

    async def list_ready(self, project: str) -> list[dict]:
        return self.tickets

    async def get_item(self, item_id: str, project: str) -> dict:
        return {
            "id": item_id,
            "name": "",
            "description": None,
            "state": "ready",
            "project": project,
        }

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        pass

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        pass


class TestWaitForDependency:
    def test_connection_success(self) -> None:
        with mock.patch("bp_agents.platform.runner.httpx.get") as mock_get:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            wait_for_dependency("http://example.com/health", "example", timeout=5)
            mock_get.assert_called_once_with("http://example.com/health", timeout=5)

    def test_accepts_any_status_code(self) -> None:
        with mock.patch("bp_agents.platform.runner.httpx.get") as mock_get:
            mock_get.return_value = mock.Mock(status_code=503)
            wait_for_dependency("http://example.com/health", "example", timeout=5)
            mock_get.assert_called_once_with("http://example.com/health", timeout=5)

    def test_retries_on_connect_error(self) -> None:
        with (
            mock.patch("bp_agents.platform.runner.httpx.get") as mock_get,
            mock.patch("tenacity.nap.sleep"),
        ):
            mock_get.side_effect = [
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                mock.Mock(status_code=200),
            ]
            wait_for_dependency("http://example.com/health", "example", timeout=5)
            assert mock_get.call_count >= 3

    def test_retries_on_http_error(self) -> None:
        with (
            mock.patch("bp_agents.platform.runner.httpx.get") as mock_get,
            mock.patch("tenacity.nap.sleep"),
        ):
            mock_get.side_effect = [
                httpx.HTTPError("server error"),
                mock.Mock(status_code=200),
            ]
            wait_for_dependency("http://example.com/health", "example", timeout=5)
            assert mock_get.call_count >= 2

    def test_timeout_raises(self) -> None:
        with mock.patch("bp_agents.platform.runner.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("always refused")
            with pytest.raises(
                RuntimeError, match="example did not become ready within 1s"
            ):
                wait_for_dependency("http://example.com/health", "example", timeout=1)


@pytest.mark.asyncio
async def test_tracker_poller_calls_on_work_then_stops() -> None:
    tracker = FakeTracker([{"id": "T-1", "description": "fix"}])

    def _state(t: dict) -> tuple[dict, str]:
        return ({"ticket_id": t["id"]}, t["id"])

    poller = TrackerPoller(tracker, "p", _state, poll_interval=0.05)
    calls: list[tuple[dict, str]] = []

    async def on_work(state: dict, thread_id: str) -> None:
        calls.append((state, thread_id))
        await poller.stop()

    await poller.start(on_work)
    assert len(calls) >= 1
    assert calls[0] == ({"ticket_id": "T-1"}, "T-1")


@pytest.mark.asyncio
async def test_tracker_poller_cancelled_on_stop() -> None:
    tracker = FakeTracker()
    poller = TrackerPoller(tracker, "p", lambda t: ({}, ""), poll_interval=0.5)

    async def on_work(state: dict, thread_id: str) -> None:
        pass

    task = asyncio.create_task(poller.start(on_work))
    await asyncio.sleep(0.1)
    task.cancel()
    done, _ = await asyncio.wait({task})
    assert done
