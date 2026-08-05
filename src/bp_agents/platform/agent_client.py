import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx


@dataclass
class Session:
    session_id: str
    base_url: str


@dataclass
class PromptResult:
    prompt_id: str
    admitted: bool


def _unwrap_payload(data: dict) -> dict:
    return data.get("data", data)


class OpenCodeClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(base_url=self.base_url)

    async def create_session(self, agent: str = "") -> Session:
        payload: dict = {}
        if agent:
            payload["agent"] = agent
        resp = await self._client.post("/api/session", json=payload)
        resp.raise_for_status()
        data = _unwrap_payload(resp.json())
        return Session(session_id=data["id"], base_url=self.base_url)

    async def prompt(self, session: Session, text: str) -> PromptResult:
        resp = await self._client.post(
            f"/api/session/{session.session_id}/prompt",
            json={"prompt": {"text": text}},
        )
        resp.raise_for_status()
        data = _unwrap_payload(resp.json())
        return PromptResult(
            prompt_id=data.get("id", ""),
            admitted=True,
        )

    async def stream_events(self, session: Session) -> AsyncIterator[dict]:
        async with self._client.stream(
            "GET", f"/api/session/{session.session_id}/event"
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    async def session_status(self, session: Session) -> dict:
        resp = await self._client.get(f"/api/session/{session.session_id}")
        resp.raise_for_status()
        return _unwrap_payload(resp.json())

    async def wait(self, session: Session) -> dict:
        resp = await self._client.post(f"/api/session/{session.session_id}/wait")
        resp.raise_for_status()
        return _unwrap_payload(resp.json())

    async def close(self) -> None:
        await self._client.aclose()
