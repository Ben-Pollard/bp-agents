import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import docker
import httpx
import pytest

from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.sandbox.config import SandboxSession


def make_handler(json_data: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status_code, json=json_data)

    return handler


def ts_ready(
    status: str,
    blocked_reason: str | None = None,
    ticket_body: str = "",
) -> dict:
    return {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "ticket_body": ticket_body,
        "status": status,
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "qa_output": None,
        "diff": None,
        "review_approved": None,
        "verification_passed": None,
        "blocked_reason": blocked_reason,
    }


def base_agent_config(**overrides) -> AgentConfig:
    base = dict(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
            "edit": {"*": "allow"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": True,
            "task": False,
            "webfetch": False,
        },
        mcps={},
    )
    base.update(overrides)
    return AgentConfig(**base)


def docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def sandbox_image_available(tag: str = "opencode-agent:latest") -> bool:
    try:
        docker.from_env().images.get(tag)
        return True
    except Exception:
        return False


def api_key_available(key: str = "OPENROUTER_API_KEY") -> bool:
    import os

    return bool(os.getenv(key))


@pytest.fixture
def target_repo() -> Path:
    tmp = Path(tempfile.mkdtemp())
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@test",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        cwd=tmp,
        capture_output=True,
        check=True,
    )
    return tmp


@pytest.fixture
def mock_sandbox() -> MagicMock:
    sandbox = MagicMock()
    sandbox.create = AsyncMock(
        return_value=SandboxSession(
            container_id="c1", port=32768, base_url="http://localhost:32768"
        )
    )
    sandbox.destroy = AsyncMock()
    return sandbox
