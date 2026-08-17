import json

import httpx
import pytest

from bp_agents.platform.agent_client import OpenCodeClient


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-1"})
        if request.url.path == "/session/sess-1/message" and request.method == "POST":
            return httpx.Response(200, json={"state": "completed"})
        if request.url.path == "/session/sess-1" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": "sess-1", "title": "test", "state": "running"},
            )
        if request.url.path == "/session/sess-1/abort" and request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/auth/openrouter" and request.method == "PUT":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def client(mock_transport: httpx.MockTransport) -> OpenCodeClient:
    return OpenCodeClient(
        "http://localhost:8080",
        client=httpx.AsyncClient(
            base_url="http://localhost:8080", transport=mock_transport
        ),
    )


async def test_create_session_returns_session(client: OpenCodeClient) -> None:
    session = await client.create_session()
    assert isinstance(session, str)
    assert session == "sess-1"


async def test_send_message_posts_to_session_message(
    client: OpenCodeClient,
) -> None:
    session = "sess-1"
    result = await client.send_message(
        session,
        parts=[{"type": "text", "text": "hi"}],
        model=("openrouter", "deepseek/deepseek-v4-flash"),
    )
    assert result["state"] == "completed"


async def test_send_message_without_tools_omits_tools_in_body() -> None:
    sent_body = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_body
        if request.url.path == "/session/sess-1/message" and request.method == "POST":
            sent_body = json.loads(request.read())
            return httpx.Response(200, json={"state": "completed"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = OpenCodeClient(
        "http://localhost:8080",
        client=httpx.AsyncClient(base_url="http://localhost:8080", transport=transport),
    )
    session = "sess-1"
    result = await client.send_message(
        session,
        parts=[{"type": "text", "text": "hi"}],
        model=("openrouter", "deepseek/deepseek-v4-flash"),
    )
    assert sent_body is not None
    assert "tools" not in sent_body
    assert result["state"] == "completed"


async def test_send_message_includes_tools_when_provided() -> None:
    sent_body = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_body
        if request.url.path == "/session/sess-1/message" and request.method == "POST":
            sent_body = json.loads(request.read())
            return httpx.Response(200, json={"state": "completed"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = OpenCodeClient(
        "http://localhost:8080",
        client=httpx.AsyncClient(base_url="http://localhost:8080", transport=transport),
    )
    session = "sess-1"
    result = await client.send_message(
        session,
        parts=[{"type": "text", "text": "hi"}],
        model=("openrouter", "deepseek/deepseek-v4-flash"),
        tools={"bash": True, "read": True, "task": False},
    )
    assert sent_body is not None
    assert sent_body["tools"] == {"bash": True, "read": True, "task": False}
    assert result["state"] == "completed"


async def test_session_status_returns_dict(client: OpenCodeClient) -> None:
    session = "sess-1"
    status = await client.session_status(session)
    assert status["id"] == "sess-1"
    assert status["state"] == "running"


async def test_abort_returns_bool(client: OpenCodeClient) -> None:
    session = "sess-1"
    result = await client.abort(session)
    assert result is True


async def test_auth_set_posts_to_auth_provider(client: OpenCodeClient) -> None:
    result = await client.auth_set("openrouter", "sk-test-key")
    assert result is True


async def test_close_closes_httpx_client(client: OpenCodeClient) -> None:
    await client.close()
