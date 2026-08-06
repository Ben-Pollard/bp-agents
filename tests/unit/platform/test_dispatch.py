import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.dispatch import (
    OUTCOME_FILENAME,
    PROVIDER_DEFINITIONS,
    dispatch,
)
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession


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
            container_id="c1", port=32768, base_url="http://localhost:32768"
        )
    )
    sb.destroy = AsyncMock()
    return sb


@pytest.fixture
def workspace() -> str:
    return tempfile.mkdtemp()


async def test_dispatch_writes_opencode_json(
    mock_sandbox: MagicMock, workspace: str
) -> None:
    outcome_data = {
        "status": "DONE",
        "summary": "Works",
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "concerns": [],
    }
    with open(os.path.join(workspace, OUTCOME_FILENAME), "w") as f:
        json.dump(outcome_data, f)

    oc_client = MagicMock()
    oc_client.auth_set = AsyncMock(return_value=True)
    oc_client.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    oc_client.send_message = AsyncMock(return_value={"state": "completed"})
    oc_client.close = AsyncMock()

    with (
        patch("bp_agents.platform.dispatch.OpenCodeClient", return_value=oc_client),
        patch(
            "bp_agents.platform.dispatch._wait_for_health", AsyncMock(return_value=True)
        ),
    ):
        result = await dispatch(
            sandbox=mock_sandbox,
            sandbox_config=_sandbox_config(),
            config=_agent_config(),
            skill="tdd",
            prompt="Do the thing",
            workspace=workspace,
            outcome_path="/data/workspace/" + OUTCOME_FILENAME,
            api_key="sk-test-key",
        )

    assert result["status"] == "DONE"
    opencode_path = os.path.join(workspace, "opencode.json")
    assert os.path.exists(opencode_path)
    with open(opencode_path) as f:
        cfg = json.load(f)
    assert "$schema" in cfg
    assert "provider" in cfg
    assert "permission" in cfg

    mock_sandbox.create.assert_called_once()
    mock_sandbox.destroy.assert_called_once()


async def test_dispatch_destroys_container_on_failure(
    mock_sandbox: MagicMock, workspace: str
) -> None:
    failing_client = MagicMock()
    failing_client.auth_set = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "401", request=MagicMock(), response=httpx.Response(401)
        )
    )
    failing_client.close = AsyncMock()

    with (
        patch(
            "bp_agents.platform.dispatch.OpenCodeClient", return_value=failing_client
        ),
        patch(
            "bp_agents.platform.dispatch._wait_for_health", AsyncMock(return_value=True)
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await dispatch(
                sandbox=mock_sandbox,
                sandbox_config=_sandbox_config(),
                config=_agent_config(),
                skill="tdd",
                prompt="Do the thing",
                workspace=workspace,
                outcome_path="/data/workspace/" + OUTCOME_FILENAME,
                api_key="sk-test-key",
            )

    mock_sandbox.destroy.assert_called_once()


async def test_dispatch_unhealthy_container_raises(
    mock_sandbox: MagicMock, workspace: str
) -> None:
    with patch(
        "bp_agents.platform.dispatch._wait_for_health", AsyncMock(return_value=False)
    ):
        with pytest.raises(RuntimeError, match="did not become healthy"):
            await dispatch(
                sandbox=mock_sandbox,
                sandbox_config=_sandbox_config(),
                config=_agent_config(),
                skill="tdd",
                prompt="Do the thing",
                workspace=workspace,
                outcome_path="/data/workspace/" + OUTCOME_FILENAME,
                api_key="sk-test-key",
            )

    mock_sandbox.destroy.assert_called_once()


async def test_dispatch_injects_credentials(
    mock_sandbox: MagicMock, workspace: str
) -> None:
    outcome_data = {
        "status": "DONE",
        "summary": "Works",
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "concerns": [],
    }
    with open(os.path.join(workspace, OUTCOME_FILENAME), "w") as f:
        json.dump(outcome_data, f)

    oc_client = MagicMock()
    oc_client.auth_set = AsyncMock(return_value=True)
    oc_client.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    oc_client.send_message = AsyncMock(return_value={"state": "completed"})
    oc_client.close = AsyncMock()

    with (
        patch("bp_agents.platform.dispatch.OpenCodeClient", return_value=oc_client),
        patch(
            "bp_agents.platform.dispatch._wait_for_health", AsyncMock(return_value=True)
        ),
    ):
        await dispatch(
            sandbox=mock_sandbox,
            sandbox_config=_sandbox_config(),
            config=_agent_config(),
            skill="tdd",
            prompt="Do the thing",
            workspace=workspace,
            outcome_path="/data/workspace/" + OUTCOME_FILENAME,
            api_key="sk-test-key",
        )

    oc_client.auth_set.assert_called_once_with("openrouter", "sk-test-key")


async def test_dispatch_provider_definitions_are_exported() -> None:
    assert "openrouter" in PROVIDER_DEFINITIONS
    assert "api" in PROVIDER_DEFINITIONS["openrouter"]
    assert "deepseek/deepseek-v4-flash" in PROVIDER_DEFINITIONS["openrouter"]["models"]


async def test_send_message_called_with_correct_model_and_tools(
    mock_sandbox: MagicMock, workspace: str
) -> None:
    outcome_data = {
        "status": "DONE",
        "summary": "Works",
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "concerns": [],
    }
    with open(os.path.join(workspace, OUTCOME_FILENAME), "w") as f:
        json.dump(outcome_data, f)

    oc_client = MagicMock()
    oc_client.auth_set = AsyncMock(return_value=True)
    oc_client.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    oc_client.send_message = AsyncMock(return_value={"state": "completed"})
    oc_client.close = AsyncMock()

    config = _agent_config()

    with (
        patch("bp_agents.platform.dispatch.OpenCodeClient", return_value=oc_client),
        patch(
            "bp_agents.platform.dispatch._wait_for_health", AsyncMock(return_value=True)
        ),
    ):
        await dispatch(
            sandbox=mock_sandbox,
            sandbox_config=_sandbox_config(),
            config=config,
            skill="tdd",
            prompt="Do the thing",
            workspace=workspace,
            outcome_path="/data/workspace/" + OUTCOME_FILENAME,
            api_key="sk-test-key",
        )

    oc_client.send_message.assert_called_once()
    args, _ = oc_client.send_message.call_args
    assert len(args) == 3 or len(args) == 4
    session_arg = args[0]
    parts_arg = args[1]
    model_arg = args[2]
    assert session_arg.session_id == "sess-1"
    assert parts_arg == [{"type": "text", "text": "Do the thing"}]
    assert model_arg == ("openrouter", "deepseek/deepseek-v4-flash")
