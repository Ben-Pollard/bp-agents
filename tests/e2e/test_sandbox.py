from __future__ import annotations

import docker
import httpx
import pytest

from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox

pytestmark = pytest.mark.e2e


_IMAGE = "python:3.12-slim"


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def _ensure_image() -> docker.DockerClient:
    client = docker.from_env()
    try:
        client.images.get(_IMAGE)
    except docker.errors.ImageNotFound:
        client.images.pull(_IMAGE)
    return client


def _proxy_available() -> bool:
    try:
        r = httpx.get("http://localhost:8080/", timeout=3)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.asyncio
async def test_sandbox_git_commands_fail_in_real_container() -> None:
    """AC-23: Git commands MUST fail inside a sandbox container with a
    clear error. Uses a real Docker container to verify the production
    code path."""
    client = _ensure_image()
    sandbox = DockerSandbox(docker_client=client)
    config = SandboxConfig(
        image=_IMAGE,
        workspace_path="/tmp",
        skills_path="/tmp",
        runtime="",
        network="",
        timeout_seconds=30,
        mem_limit="128m",
        cpu_count=1,
    )
    session = await sandbox.create(config)
    try:
        exit_code, output = await sandbox.exec_run(session.container_id, "git status")
        assert exit_code != 0, "git should not be available in sandbox"
        assert (
            b"not found" in output.lower() or b"not a command" in output.lower()
        ), f"expected 'not found' error, got: {output!r}"
    finally:
        await sandbox.destroy(session.container_id)


@pytest.mark.skipif(
    not (_docker_available() and _proxy_available()),
    reason="Docker or egress-proxy not available",
)
@pytest.mark.asyncio
async def test_sandbox_can_reach_pypi_through_proxy() -> None:
    """AC-21: Sandbox can reach PyPI through the egress proxy."""
    client = _ensure_image()
    sandbox = DockerSandbox(docker_client=client)
    config = SandboxConfig(
        image=_IMAGE,
        workspace_path="/tmp",
        skills_path="/tmp",
        runtime="",
        timeout_seconds=60,
        mem_limit="256m",
        cpu_count=1,
    )
    session = await sandbox.create(config)
    try:
        exit_code, output = await sandbox.exec_run(
            session.container_id,
            "sh -c 'pip install --dry-run requests 2>&1'",
        )
        assert exit_code == 0, f"pip install failed: {output!r}"
    finally:
        await sandbox.destroy(session.container_id)


@pytest.mark.skipif(
    not (_docker_available() and _proxy_available()),
    reason="Docker or egress-proxy not available",
)
@pytest.mark.asyncio
async def test_sandbox_cannot_reach_arbitrary_internet() -> None:
    """AC-22: Sandbox cannot reach arbitrary internet (e.g. example.com)
    through the egress proxy. The proxy returns a 403 or connection
    refused for non-allowlisted hosts."""
    client = _ensure_image()
    sandbox = DockerSandbox(docker_client=client)
    config = SandboxConfig(
        image=_IMAGE,
        workspace_path="/tmp",
        skills_path="/tmp",
        runtime="",
        timeout_seconds=30,
        mem_limit="128m",
        cpu_count=1,
    )
    session = await sandbox.create(config)
    try:
        exit_code, output = await sandbox.exec_run(
            session.container_id,
            (
                'python -c "'
                "import urllib.request, urllib.error;"
                "try:"
                "  r = urllib.request.urlopen('https://example.com', timeout=10);"
                "  print(r.status)"
                "except urllib.error.HTTPError as e:"
                "  print('HTTP_ERROR', e.code)"
                "except Exception as e:"
                "  print('UNEXPECTED', type(e).__name__)"
                '" 2>&1'
            ),
        )
        output_str = output.decode().strip()
        assert exit_code == 0, f"python command failed: {output_str!r}"
        assert (
            "HTTP_ERROR 403" in output_str
        ), f"expected proxy to block example.com with 403, got: {output_str!r}"
    finally:
        await sandbox.destroy(session.container_id)
