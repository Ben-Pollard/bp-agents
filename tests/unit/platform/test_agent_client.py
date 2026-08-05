import json

import httpx
import pytest

from bp_agents.platform.agent_client import OpenCodeClient, PromptResult, Session


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-1"})
        if (
            request.url.path == "/api/session/sess-1/prompt"
            and request.method == "POST"
        ):
            return httpx.Response(200, json={"id": "prompt-1"})
        if request.url.path == "/api/session/sess-1" and request.method == "GET":
            return httpx.Response(
                200,
                json={"id": "sess-1", "title": "test", "state": "running"},
            )
        if request.url.path == "/api/session/sess-1/event" and request.method == "GET":
            body = "data: " + json.dumps({"type": "message", "text": "hi"}) + "\n\n"
            return httpx.Response(200, content=body.encode())
        if request.url.path == "/api/session/sess-1/wait" and request.method == "POST":
            return httpx.Response(200, json={"id": "sess-1", "state": "completed"})
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
    assert isinstance(session, Session)
    assert session.session_id == "sess-1"
    assert session.base_url == "http://localhost:8080"


async def test_create_session_sends_agent(client: OpenCodeClient) -> None:
    session = await client.create_session(agent="code-review")
    assert session.session_id == "sess-1"


async def test_prompt_returns_prompt_result(client: OpenCodeClient) -> None:
    session = Session(session_id="sess-1", base_url="http://localhost:8080")
    result = await client.prompt(session, "write a test")
    assert isinstance(result, PromptResult)
    assert result.prompt_id == "prompt-1"
    assert result.admitted is True


async def test_prompt_uses_session_id_in_path(client: OpenCodeClient) -> None:
    session = Session(session_id="sess-1", base_url="http://localhost:8080")
    result = await client.prompt(session, "hi")
    assert result.prompt_id == "prompt-1"


async def test_session_status_returns_dict(client: OpenCodeClient) -> None:
    session = Session(session_id="sess-1", base_url="http://localhost:8080")
    status = await client.session_status(session)
    assert status["id"] == "sess-1"
    assert status["state"] == "running"


async def test_stream_events_yields_dicts(client: OpenCodeClient) -> None:
    session = Session(session_id="sess-1", base_url="http://localhost:8080")
    events = [event async for event in client.stream_events(session)]
    assert events == [{"type": "message", "text": "hi"}]


async def test_wait_returns_status(client: OpenCodeClient) -> None:
    session = Session(session_id="sess-1", base_url="http://localhost:8080")
    status = await client.wait(session)
    assert status["id"] == "sess-1"


async def test_close_closes_httpx_client(client: OpenCodeClient) -> None:
    await client.close()
