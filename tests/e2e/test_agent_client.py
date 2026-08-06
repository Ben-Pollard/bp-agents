"""E2E tests for OpenCodeClient against a real opencode serve process."""

import asyncio
import json
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
            r = httpx.get(f"{base_url}/api/health", timeout=2)
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

        session = await client.create_session()
        assert session.session_id, "create_session must return a session_id"
        assert session.session_id.startswith("ses_"), "session_id must start with ses_"

        status = await client.session_status(session)
        assert isinstance(status, dict), "session_status must return a dict"
        assert status["id"] == session.session_id

        auth_ok = await client.auth_set("openrouter", "test-key")
        assert auth_ok is True, "auth_set must return True"

        send_task = asyncio.create_task(
            client.send_message(
                session,
                [{"type": "text", "text": "list files"}],
                ("openrouter", "deepseek/deepseek-v4-flash"),
            )
        )
        await asyncio.sleep(1)
        abort_ok = await client.abort(session)
        assert abort_ok is True, "abort must return True"

        try:
            await asyncio.wait_for(send_task, timeout=3)
        except (asyncio.TimeoutError, httpx.HTTPStatusError, json.JSONDecodeError):
            pass

        await client.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
