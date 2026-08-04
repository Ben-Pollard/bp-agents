from unittest import mock

import httpx
import pytest

from bp_agents.orchestrator.main import POLL_INTERVAL, main, wait_for_dependency
from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState


class FakeTracker(Tracker):
    async def list_ready(self, project: str) -> list[dict]:
        return []

    async def get_item(self, item_id: str, project: str) -> dict:
        return {
            "id": item_id,
            "name": "",
            "description": None,
            "state": TicketState.READY.value,
            "project": project,
        }

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        pass

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        pass


class TestWaitForDependency:
    def test_connection_success(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            mock_get.assert_called_once_with("http://example.com/health", timeout=5)

    def test_accepts_any_status_code(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_get.return_value = mock.Mock(status_code=503)

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            mock_get.assert_called_once_with("http://example.com/health", timeout=5)

    def test_retries_on_connect_error(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_get.side_effect = [
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                mock.Mock(status_code=200),
            ]

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            assert mock_get.call_count >= 3

    def test_retries_on_http_error(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_get.side_effect = [
                httpx.HTTPError("server error"),
                mock.Mock(status_code=200),
            ]

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            assert mock_get.call_count >= 2

    def test_timeout_raises(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("always refused")

            with pytest.raises(
                RuntimeError, match="example did not become ready within 1s"
            ):
                wait_for_dependency("http://example.com/health", "example", timeout=1)


class TestPollInterval:
    def test_poll_interval_has_default(self) -> None:
        assert isinstance(POLL_INTERVAL, int)
        assert POLL_INTERVAL > 0


class TestMain:
    def test_main_logs_ready_when_all_dependencies_up(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)

        with (
            mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get,
            mock.patch("bp_agents.orchestrator.main.time.sleep") as mock_sleep,
            mock.patch("bp_agents.orchestrator.main.time.time") as mock_time,
        ):
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            mock_time.side_effect = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            mock_sleep.side_effect = KeyboardInterrupt

            main(tracker=FakeTracker())

            records = [r.message for r in caplog.records]
            assert "orchestrator ready" in records
            assert "orchestrator shutting down" in records

    def test_main_raises_when_dependency_fails(self) -> None:
        with (
            mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get,
            mock.patch("bp_agents.orchestrator.main.time.time") as mock_time,
            mock.patch("bp_agents.orchestrator.main.time.sleep"),
        ):
            mock_get.side_effect = httpx.ConnectError("always refused")
            mock_time.side_effect = [0, 120]

            with pytest.raises(
                RuntimeError, match="Redmine did not become ready within 120s"
            ):
                main(tracker=FakeTracker())
