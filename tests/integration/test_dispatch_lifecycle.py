"""Integration test: full dispatch lifecycle with a fake opencode server.

QA found POST /session/{id}/message returns immediately and session
stays "running" — send_message must poll until completion.
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.dispatch import OUTCOME_FILENAME, dispatch
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession


class _TrackingHandler:
    def __init__(self, poll_count: int = 2):
        self.session_id = "ses-test-1"
        self.poll_calls = 0
        self.poll_count = poll_count
        self.abort_called = False
        self.auth_called = False
        self.msg_received = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"healthy": True})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": self.session_id})
        if request.url.path == f"/session/{self.session_id}":
            if request.method == "GET":
                self.poll_calls += 1
                if self.poll_calls >= self.poll_count:
                    return httpx.Response(
                        200, json={"id": self.session_id, "state": "completed"}
                    )
                return httpx.Response(
                    200, json={"id": self.session_id, "state": "running"}
                )
            return httpx.Response(404)
        if (
            request.url.path == f"/session/{self.session_id}/message"
            and request.method == "POST"
        ):
            self.msg_received = True
            return httpx.Response(200, json={"state": "running"})
        if (
            request.url.path == f"/session/{self.session_id}/abort"
            and request.method == "POST"
        ):
            self.abort_called = True
            return httpx.Response(200, json={"ok": True})
        if request.url.path.startswith("/auth/") and request.method == "PUT":
            self.auth_called = True
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


def _agent_config() -> AgentConfig:
    return AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": True},
        mcps={},
    )


def _sandbox_config() -> SandboxConfig:
    return SandboxConfig(
        image="symphony-agent:latest",
        workspace_path="/tmp/ws",
        skills_path="/tmp/skills",
        runtime="",
        timeout_seconds=60,
    )


@pytest.fixture
def mock_sandbox() -> MagicMock:
    sb = MagicMock()
    sb.create = AsyncMock(
        return_value=SandboxSession(
            container_id="c1", port=9999, base_url="http://localhost:9999"
        )
    )
    sb.destroy = AsyncMock()
    return sb


@pytest.mark.asyncio
async def test_dispatch_lifecycle_completes_with_polling(
    mock_sandbox: MagicMock,
) -> None:
    handler = _TrackingHandler(poll_count=3)
    transport = httpx.MockTransport(handler.handle)

    async with httpx.AsyncClient(
        base_url="http://localhost:9999", transport=transport
    ) as client:
        oc_client = OpenCodeClient(
            "http://localhost:9999",
            client=client,
        )

        workspace = tempfile.mkdtemp()

        outcome_data = {
            "status": "DONE",
            "summary": "Works",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        with open(os.path.join(workspace, OUTCOME_FILENAME), "w") as f:
            json.dump(outcome_data, f)

        cfg = _sandbox_config()
        cfg.workspace_path = workspace

        with patch(
            "bp_agents.platform.dispatch._wait_for_health",
            AsyncMock(return_value=True),
        ):
            result = await dispatch(
                sandbox=mock_sandbox,
                sandbox_config=cfg,
                config=_agent_config(),
                skill="tdd",
                prompt="Do the thing",
                workspace=workspace,
                outcome_path="/data/" + OUTCOME_FILENAME,
                api_key="sk-test-key",
                opencode_client=oc_client,
            )

    assert result["status"] == "DONE"
    assert handler.msg_received, "POST /message must be called"
    assert handler.abort_called, "abort must be called during cleanup"
    assert handler.auth_called, "auth_set must be called"
    assert (
        handler.poll_calls >= 2
    ), f"expected at least 2 poll calls, got {handler.poll_calls}"
    mock_sandbox.destroy.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_polls_when_message_returns_running(
    mock_sandbox: MagicMock,
) -> None:
    handler = _TrackingHandler(poll_count=5)
    transport = httpx.MockTransport(handler.handle)

    async with httpx.AsyncClient(
        base_url="http://localhost:9999", transport=transport
    ) as client:
        oc_client = OpenCodeClient(
            "http://localhost:9999",
            client=client,
        )

        workspace = tempfile.mkdtemp()

        outcome_data = {
            "status": "DONE",
            "summary": "Works",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        with open(os.path.join(workspace, OUTCOME_FILENAME), "w") as f:
            json.dump(outcome_data, f)

        cfg = _sandbox_config()
        cfg.workspace_path = workspace

        with patch(
            "bp_agents.platform.dispatch._wait_for_health",
            AsyncMock(return_value=True),
        ):
            result = await dispatch(
                sandbox=mock_sandbox,
                sandbox_config=cfg,
                config=_agent_config(),
                skill="tdd",
                prompt="Do the thing",
                workspace=workspace,
                outcome_path="/data/" + OUTCOME_FILENAME,
                api_key="sk-test-key",
                opencode_client=oc_client,
            )

    assert result["status"] == "DONE"
    assert (
        handler.poll_calls >= 4
    ), f"expected at least 4 poll calls before completion, got {handler.poll_calls}"
    mock_sandbox.destroy.assert_called_once()
