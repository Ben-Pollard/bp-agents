"""E2E test: full pathway from Redmine ticket to sandbox agent activity.

Composes the orchestator stack (redmine + egress-proxy + orchestrator),
creates a Redmine ticket, and monitors orchestrator logs until the
sandbox agent produces its first output (LLM call, tool invocation, or
response), confirming the pathway:
  ticket → poller → graph → TddNode → dispatch → sandbox → first message

This tests the real networking: the orchestrator runs inside Docker on
bp_agents, dispatch creates the sandbox on the same network, the sandbox
routes outbound traffic through the egress proxy, and --print-logs output
streams back to the orchestrator's stdout.
"""

import logging
import os
import re
import subprocess
import time
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

_SANDBOX_IMAGE = "bp-agents-test-sandbox:latest"
_REDMINE_URL = "http://localhost:8082"
_REDMINE_AUTH = ("admin", "admin")
_POLL_INTERVAL = 5
_LOG_TIMEOUT = 180
_CONTAINER_NAME_PATTERN = r"bp.agents-orchestrator-\d+"

logger = logging.getLogger(__name__)


def _compose_up(service: str) -> None:
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", service],
        check=True,
        capture_output=True,
    )


def _compose_run(service: str, *args: str) -> None:
    subprocess.run(
        ["docker", "compose", "run", "--rm", service, *args],
        check=True,
        capture_output=True,
    )


def _compose_down() -> None:
    subprocess.run(
        ["docker", "compose", "down", "-t", "5"],
        check=False,
        capture_output=True,
    )


def _wait_for_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not become ready within {timeout}s")


def _orchestrator_container_id() -> str:
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}} {{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        cid, name = line.split(" ", 1)
        if re.search(_CONTAINER_NAME_PATTERN, name):
            return cid
    raise RuntimeError("orchestrator container not found")


def _read_logs_since(container_id: str, since: float) -> str:
    since_str = str(int(since))
    result = subprocess.run(
        ["docker", "logs", "--since", since_str, container_id],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def _wait_for_orchestrator_ready(container_id: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        logs = _read_logs_since(container_id, time.monotonic() - 10)
        if "runner starting" in logs.lower():
            return
        time.sleep(2)
    raise RuntimeError(
        "orchestrator did not start within %ss:\n%s",
        timeout,
        _read_logs_since(container_id, time.monotonic() - 60),
    )


def _container_logs_contain(container_id: str, marker: str) -> list[str]:
    result = subprocess.run(
        ["docker", "logs", "--tail", "500", container_id],
        capture_output=True,
        text=True,
    )
    return [
        line for line in (result.stdout + result.stderr).splitlines() if marker in line
    ]


@pytest.fixture(scope="module")
def e2e_stack() -> Generator[Path, None, None]:
    repo = Path("/tmp/opencode/e2e-test-target")
    if repo.exists():
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "/tmp/opencode:/data",
                "alpine:latest",
                "rm",
                "-rf",
                f"/data/{repo.name}",
            ],
            capture_output=True,
            check=False,
        )
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
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
        cwd=repo,
        check=True,
        capture_output=True,
    )

    os.environ["BP_TARGET_REPO_PATH"] = str(repo)
    os.environ["BP_SANDBOX_IMAGE"] = _SANDBOX_IMAGE
    os.environ["BP_SANDBOX_RUNTIME"] = ""
    os.environ["BP_LOG_LEVEL"] = "DEBUG"
    os.environ["BP_POLL_INTERVAL"] = str(_POLL_INTERVAL)

    logger.info("Composing egress-proxy, redmine-db, redmine...")
    _compose_up("egress-proxy")
    _compose_up("redmine-db")
    _compose_up("redmine")
    _wait_for_http(_REDMINE_URL)
    _compose_run("redmine-setup")

    logger.info("Starting orchestrator...")
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "--build", "orchestrator"],
        check=True,
        capture_output=True,
    )

    yield repo

    _compose_down()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "/tmp/opencode:/data",
            "alpine:latest",
            "rm",
            "-rf",
            f"/data/{repo.name}",
        ],
        capture_output=True,
        check=False,
    )


@pytest.mark.e2e
def test_full_pathway_produces_agent_output(e2e_stack: Path) -> None:
    cid = _orchestrator_container_id()
    _wait_for_orchestrator_ready(cid)

    r = httpx.get(
        f"{_REDMINE_URL}/users/current.json?include=api_key", auth=_REDMINE_AUTH
    )
    r.raise_for_status()
    api_key = r.json()["user"]["api_key"]

    r = httpx.get(f"{_REDMINE_URL}/issue_statuses.json", auth=_REDMINE_AUTH)
    r.raise_for_status()
    statuses = {s["name"]: s["id"] for s in r.json()["issue_statuses"]}
    ready_id = statuses.get("ready")
    assert ready_id is not None, "Redmine must have a 'ready' status after bootstrap"

    r = httpx.post(
        f"{_REDMINE_URL}/issues.json",
        headers={"X-Redmine-API-Key": api_key, "Content-Type": "application/json"},
        json={
            "issue": {
                "project_id": "default",
                "subject": "Write a hello function",
                "description": "write a hello() function that returns 'hello world' and a test for it",
                "status_id": ready_id,
            }
        },
    )
    r.raise_for_status()
    issue_id = r.json()["issue"]["id"]
    logger.info("Created Redmine ticket %s", issue_id)

    deadline = time.monotonic() + _LOG_TIMEOUT
    markers = [
        "stream providerID=",
        "evaluated permission",
        "exiting loop",
        "[sandbox]",
    ]

    while time.monotonic() < deadline:
        logs = _container_logs_contain(cid, "[sandbox]")
        if logs:
            agent_lines = [line for line in logs if any(m in line for m in markers)]
            if agent_lines:
                logger.info("Agent activity detected in orchestrator logs")
                for line in agent_lines[:5]:
                    logger.info("  %s", line.strip())
                return

        time.sleep(1)

    all_logs = _container_logs_contain(cid, "")
    log_snippet = "\n".join(all_logs[-50:])
    pytest.fail(
        f"No agent activity detected within {_LOG_TIMEOUT}s.\n"
        f"Last 50 orchestrator log lines:\n{log_snippet}"
    )
