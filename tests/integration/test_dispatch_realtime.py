"""Integration test: real dispatch against sandboxed opencode serve + real LLM.

Creates a sandbox container running opencode serve, dispatches a TDD agent
with a simple "say hello" prompt, and verifies the session completes with
a real outcome from the LLM.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

import docker
import pytest

from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.dispatch import OUTCOME_FILENAME, dispatch
from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.platform.sandbox.egress import EgressPolicy

_SANDBOX_IMAGE = os.getenv("BP_SANDBOX_IMAGE", "opencode-agent:latest")


def _sandbox_image_available() -> bool:
    try:
        docker.from_env().images.get(_SANDBOX_IMAGE)
        return True
    except Exception:
        return False


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def _api_key_available() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def _agent_config() -> AgentConfig:
    return AgentConfig(
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


pytestmark = [
    pytest.mark.skipif(
        not _docker_available(),
        reason="Docker not available",
    ),
    pytest.mark.skipif(
        not _sandbox_image_available(),
        reason=f"Sandbox image {_SANDBOX_IMAGE} not found — run `docker build -t {_SANDBOX_IMAGE} -f Dockerfile.sandbox .`",
    ),
    pytest.mark.skipif(
        not _api_key_available(),
        reason="OPENROUTER_API_KEY not set — LLM calls will fail",
    ),
]


@pytest.mark.asyncio
async def test_dispatch_say_hello_against_real_sandbox(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    workspace = tempfile.mkdtemp()
    skills_dir = Path(tempfile.mkdtemp())
    skill_dir = skills_dir / "tdd"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# TDD skill - write code and tests")

    sandbox = DockerSandbox(egress_policy=EgressPolicy())
    cfg = SandboxConfig(
        image=_SANDBOX_IMAGE,
        workspace_path=workspace,
        skills_path=str(skills_dir),
        runtime="",
        timeout_seconds=120,
        network="bp_agents",
        http_proxy="http://172.20.0.10:8080",
        https_proxy="http://172.20.0.10:8080",
        dns_servers=["8.8.8.8"],
        env={"OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"]},
        command=["opencode", "serve", "--port", "8080", "--hostname", "0.0.0.0"],
    )

    outcome_path = "/data/" + OUTCOME_FILENAME

    try:
        result = await dispatch(
            sandbox=sandbox,
            sandbox_config=cfg,
            config=_agent_config(),
            skill="tdd",
            prompt=json.dumps(
                {
                    "stage": "tdd",
                    "direction": "input",
                    "payload": {
                        "skill": "tdd",
                        "ticket": {
                            "id": "INT-TEST",
                            "body": "write a hello() function that returns 'hello world' and a test for it",
                        },
                        "context": {},
                    },
                }
            ),
            workspace=workspace,
            outcome_path=outcome_path,
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    except Exception:
        caplog_text = "\n".join(
            f"{r.levelname}:{r.name}:{r.message}" for r in caplog.records
        )
        pytest.fail(f"dispatch raised. logs:\n{caplog_text}")

    assert isinstance(result, dict), f"expected dict outcome, got {type(result)}"
    assert "status" in result, f"outcome missing 'status': {result}"
    assert "summary" in result, f"outcome missing 'summary': {result}"
    assert result["status"] in ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL")

    records_text = "\n".join(r.message for r in caplog.records)
    assert "dispatching tdd" in records_text, "AC-01: missing dispatch log"
    assert "tdd output" in records_text, "AC-15: missing output contract log"
