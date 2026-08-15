"""Integration test: ticket submission → sandbox → agent first message.

Builds the sandbox image from Dockerfile.sandbox, creates a real container
running opencode serve --print-logs, dispatches a TDD prompt, and verifies
the full lifecycle: health check, auth, session creation, message send,
polling for completion, outcome.json reading, and --print-logs streaming
back to the orchestrator.

This is the test that automates what would otherwise require manual
docker build + docker run + manual API calls every time the pathway changes.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import docker
import pytest

from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.dispatch import OUTCOME_FILENAME, dispatch
from bp_agents.platform.sandbox.config import WORKSPACE_MOUNT_PATH, SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.platform.sandbox.egress import EgressPolicy
from bp_agents.workflows.sdd.nodes.tdd import (
    build_input_contract,
    input_contract_to_prompt,
)

_TEST_IMAGE_TAG = "bp-agents-test-sandbox:latest"


def _build_sandbox_image() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = root / "Dockerfile.sandbox"
    context = root
    subprocess.run(
        ["docker", "build", "-t", _TEST_IMAGE_TAG, "-f", str(dockerfile), "."],
        cwd=context,
        check=True,
        capture_output=True,
        timeout=300,
    )


def _image_available() -> bool:
    try:
        docker.from_env().images.get(_TEST_IMAGE_TAG)
        return True
    except docker.errors.ImageNotFound:
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
        not _api_key_available(),
        reason="OPENROUTER_API_KEY not set",
    ),
]


@pytest.fixture(scope="session")
def sandbox_image() -> None:
    if not _image_available():
        _build_sandbox_image()
    assert _image_available(), f"failed to build {_TEST_IMAGE_TAG}"


@pytest.mark.asyncio
async def test_ticket_to_sandbox_first_message(
    sandbox_image: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    workspace = tempfile.mkdtemp()
    skills_dir = Path(tempfile.mkdtemp())
    skill_dir = skills_dir / "tdd"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# TDD skill\n\n"
        "Implement the ticket. Use test-driven development.\n"
        "When done, write the outcome JSON to the path in outcome_path env var "
        "with fields: status (DONE|BLOCKED|FAIL), summary, concerns.\n"
    )

    sandbox = DockerSandbox(egress_policy=EgressPolicy())
    cfg = SandboxConfig(
        image=_TEST_IMAGE_TAG,
        workspace_path=workspace,
        skills_path=str(skills_dir),
        runtime="",
        timeout_seconds=180,
        env={"OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"]},
        command=[
            "opencode",
            "serve",
            "--port",
            "8080",
            "--print-logs",
            "--hostname",
            "0.0.0.0",
        ],
    )

    outcome_path = WORKSPACE_MOUNT_PATH + "/" + OUTCOME_FILENAME

    input_contract = build_input_contract(
        "FMS-1",
        "write a hello() function that returns 'hello world' and a test for it",
    )
    prompt = input_contract_to_prompt(input_contract, outcome_path)

    try:
        result = await dispatch(
            sandbox=sandbox,
            sandbox_config=cfg,
            config=_agent_config(),
            skill="tdd",
            prompt=prompt,
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
    assert "[sandbox]" in records_text, (
        "sandbox --print-logs output must be streamed back via "
        "_stream_container_logs. This verifies the print-logs "
        "pathway from sandbox to orchestrator is working."
    )
    assert "opencode server listening" in records_text, (
        "opencode --print-logs startup message must appear in the "
        "streamed sandbox logs, confirming the server started."
    )
    assert "outcome_path" in records_text, (
        "the outcome_path instruction must appear in the dispatcher logs, "
        "confirming the agent was told where to write its output."
    )
    assert "health check passed" in records_text, (
        "health check must pass within retry budget. This confirms the "
        "orchestrator can reach the sandbox's opencode HTTP API."
    )
    assert "read outcome:" in records_text, (
        "dispatch must read the outcome.json written by the agent inside "
        "the sandbox. This confirms the workspace mount works."
    )
