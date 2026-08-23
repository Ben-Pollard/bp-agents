"""E2E test: Redmine ticket → TDD sandbox → MCP contract fulfilled.

Composes the orchestrator stack, creates a Redmine ticket, waits for the
TDD stage to complete with a validated MCP contract. Exercises the real
networking (sandbox_net, egress proxy, DNS) that mocks can't catch.
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
_LOG_TIMEOUT = 300
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


def _orchestrator_logs(container_id: str) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", "2000", container_id],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def _wait_for_orchestrator_ready(container_id: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        logs = _orchestrator_logs(container_id)
        if "runner starting" in logs.lower():
            return
        time.sleep(2)
    raise RuntimeError(f"orchestrator did not start within {timeout}s")


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
def test_full_pipeline_completes_all_stages(e2e_stack: Path) -> None:
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
                "subject": "Write a factorial function",
                "description": (
                    "Write a function factorial(n) that returns n! "
                    "iteratively. Handle n=0. Write tests first."
                ),
                "status_id": ready_id,
            }
        },
    )
    r.raise_for_status()
    issue_id = r.json()["issue"]["id"]
    logger.info("Created Redmine ticket %s", issue_id)

    deadline = time.monotonic() + _LOG_TIMEOUT

    while time.monotonic() < deadline:
        logs = _orchestrator_logs(cid)
        if "tdd output  contract=" in logs:
            logger.info("  TDD contract fulfilled for ticket %s", issue_id)
            break
        time.sleep(5)
    else:
        all_logs = _orchestrator_logs(cid)
        pytest.fail(
            f"TDD did not complete within {_LOG_TIMEOUT}s.\n"
            f"Last 30 log lines:\n" + "\n".join(all_logs.splitlines()[-30:])
        )

    r = httpx.get(
        f"{_REDMINE_URL}/issues/{issue_id}.json",
        headers={"X-Redmine-API-Key": api_key},
    )
    r.raise_for_status()
    final_status = r.json()["issue"]["status"]["name"]
    assert final_status in (
        "awaiting_review",
        "awaiting_verification",
        "awaiting_approval",
    ), f"Expected ticket to advance past implementing, got {final_status}"
