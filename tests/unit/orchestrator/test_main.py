from unittest import mock

import httpx
import pytest

from bp_agents.orchestrator.main import POLL_INTERVAL, wait_for_dependency


class TestWaitForDependency:
    def test_connection_success(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            mock_get.assert_called_once_with("http://example.com/health", timeout=5)

    def test_retries_then_succeeds(self) -> None:
        with mock.patch("bp_agents.orchestrator.main.httpx.get") as mock_get:
            mock_get.side_effect = [
                httpx.ConnectError("refused"),
                httpx.ConnectError("refused"),
                mock.Mock(status_code=200),
            ]

            wait_for_dependency("http://example.com/health", "example", timeout=5)

            assert mock_get.call_count == 3

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
            mock.patch("bp_agents.orchestrator.main.PlaneTracker") as mock_tracker_cls,
        ):
            mock_response = mock.Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            mock_time.side_effect = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            mock_sleep.side_effect = KeyboardInterrupt
            mock_tracker = mock.AsyncMock()
            mock_tracker.list_ready = mock.AsyncMock(return_value=[])
            mock_tracker_cls.return_value = mock_tracker

            from bp_agents.orchestrator.main import main

            main()

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

            from bp_agents.orchestrator.main import main

            with pytest.raises(
                RuntimeError, match="Plane did not become ready within 120s"
            ):
                main()
