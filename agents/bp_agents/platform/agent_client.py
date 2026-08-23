import asyncio
import json
import logging
from typing import TypeAlias

import httpx

logger = logging.getLogger(__name__)

Session: TypeAlias = str

SESSION_POLL_INTERVAL = 2.0
SESSION_TIMEOUT = 600


class OpenCodeClient:
    """httpx wrapper for opencode serve HTTP API."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=SESSION_TIMEOUT
            )

    async def auth_set(self, provider_id: str, api_key: str) -> bool:
        logger.debug("auth_set provider=%s key_len=%d", provider_id, len(api_key))
        resp = await self._client.put(
            f"/auth/{provider_id}",
            json={"type": "api", "key": api_key},
        )
        resp.raise_for_status()
        logger.debug("auth_set response: %d %s", resp.status_code, resp.text[:500])
        return resp.status_code == 200

    async def create_session(self) -> Session:
        resp = await self._client.post("/session")
        resp.raise_for_status()
        parsed = resp.json()
        logger.debug("create_session response: %s", parsed)
        return parsed.get("data", parsed)["id"]

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
        logger.debug(
            "send_message session=%s body=%s",
            session,
            json.dumps(body),
        )
        resp = await self._client.post(
            f"/session/{session}/message",
            json=body,
        )
        resp.raise_for_status()

        parsed = resp.json()
        msg = parsed.get("data", parsed)
        logger.debug(
            "send_message response session=%s state=%s finish=%s body=%s",
            session,
            msg.get("state", "?"),
            msg.get("info", {}).get("finish", "?"),
            json.dumps(msg),
        )
        msg_state = msg.get("state", "")
        msg_finish = msg.get("info", {}).get("finish", "")
        if (msg_state and msg_state != "running") or (msg_finish == "stop"):
            return msg

        elapsed = 0.0
        first_poll = True
        while elapsed < SESSION_TIMEOUT:
            status = await self.session_status(session)
            state = status.get("state", "")
            finish = status.get("info", {}).get("finish", "")
            if first_poll:
                logger.debug(
                    "session_status first_poll session=%s state=%s finish=%s body=%s",
                    session,
                    state,
                    finish,
                    json.dumps(status),
                )
                first_poll = False
            if (state and state != "running") or (finish == "stop"):
                return status
            await asyncio.sleep(SESSION_POLL_INTERVAL)
            elapsed += SESSION_POLL_INTERVAL

        return msg

    async def session_status(self, session: Session) -> dict:
        resp = await self._client.get(f"/session/{session}")
        resp.raise_for_status()
        parsed = resp.json()
        data = parsed.get("data", parsed)
        logger.debug(
            "session_status session=%s state=%s finish=%s",
            session,
            data.get("state", "?"),
            data.get("info", {}).get("finish", "?"),
        )
        return data

    async def abort(self, session: Session) -> bool:
        logger.debug("abort session=%s", session)
        resp = await self._client.post(f"/session/{session}/abort")
        resp.raise_for_status()
        return resp.status_code == 200

    async def close(self) -> None:
        await self._client.aclose()
