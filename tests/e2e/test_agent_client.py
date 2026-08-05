"""E2E tests for OpenCodeClient against a real opencode serve process."""

import subprocess
import time

import httpx
import pytest

from bp_agents.platform.agent_client import OpenCodeClient

pytestmark = pytest.mark.e2e


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _opencode_available() -> bool:
    try:
        subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_until_ready(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/session", timeout=2)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("opencode serve did not become ready")


@pytest.mark.skipif(
    not _opencode_available(),
    reason="opencode CLI not available",
)
@pytest.mark.asyncio
async def test_open_code_client_http_contract_against_real_server() -> None:
    """OpenCodeClient create_session, prompt, and session_status work against
    a real opencode serve process (AC-01, AC-02, AC-14, AC-15).

    This is the missing E2E level: exercises the real HTTP contract between
    OpenCodeClient and opencode serve rather than a fake transport.
    """
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    proc = subprocess.Popen(
        ["opencode", "serve", "--port", str(port), "--print-logs", "--pure"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _wait_until_ready(base_url)

        client = OpenCodeClient(base_url)

        session = await client.create_session(agent="builder")
        assert session.session_id, "create_session must return a session_id"

        result = await client.prompt(
            session, "Write a hello world function with a test"
        )
        assert result.admitted is True, "prompt must be admitted"
        assert result.prompt_id, "prompt must return a prompt_id"

        status = await client.session_status(session)
        assert isinstance(status, dict), "session_status must return a dict"

        await client.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
