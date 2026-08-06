import asyncio
from dataclasses import dataclass

import httpx


@dataclass
class Session:
    session_id: str


SESSION_POLL_INTERVAL = 2.0
SESSION_TIMEOUT = 600


def _unwrap_payload(data: dict) -> dict:
    return data.get("data", data)


class OpenCodeClient:
    """httpx wrapper for opencode serve HTTP API."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(base_url=self.base_url)

    async def auth_set(self, provider_id: str, api_key: str) -> bool:
        resp = await self._client.put(
            f"/auth/{provider_id}",
            json={"type": "api", "key": api_key},
        )
        resp.raise_for_status()
        return resp.status_code == 200

    async def create_session(self) -> Session:
        resp = await self._client.post("/session")
        resp.raise_for_status()
        data = _unwrap_payload(resp.json())
        return Session(session_id=data["id"])

    async def send_message(
        self,
        session: Session,
        parts: list[dict],
        model: tuple[str, str],
        tools: dict[str, bool] | None = None,
    ) -> dict:
        body: dict = {
            "model": {"providerID": model[0], "modelID": model[1]},
            "parts": parts,
        }
        if tools is not None:
            body["tools"] = tools
        resp = await self._client.post(
            f"/session/{session.session_id}/message",
            json=body,
        )
        resp.raise_for_status()

        msg = _unwrap_payload(resp.json())
        msg_state = msg.get("state", "")
        if msg_state and msg_state != "running":
            return msg

        elapsed = 0.0
        while elapsed < SESSION_TIMEOUT:
            status = await self.session_status(session)
            state = status.get("state", "")
            if state and state != "running":
                return status
            await asyncio.sleep(SESSION_POLL_INTERVAL)
            elapsed += SESSION_POLL_INTERVAL

        return msg

    async def session_status(self, session: Session) -> dict:
        resp = await self._client.get(f"/session/{session.session_id}")
        resp.raise_for_status()
        return _unwrap_payload(resp.json())

    async def abort(self, session: Session) -> bool:
        resp = await self._client.post(f"/session/{session.session_id}/abort")
        resp.raise_for_status()
        return resp.status_code == 200

    async def close(self) -> None:
        await self._client.aclose()
