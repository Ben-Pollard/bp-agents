from dataclasses import dataclass
from datetime import datetime

import httpx

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState


@dataclass
class Ticket:
    id: str
    name: str
    description: str | None
    state: TicketState
    project: str
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None


class PlaneTracker(Tracker):
    def __init__(self, base_url: str, api_key: str, workspace_slug: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.workspace_slug = workspace_slug
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
        )

    async def list_ready(self, project: str) -> list[dict]:
        resp = await self._client.get(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues",
            params={"state_group": "backlog"},
        )
        resp.raise_for_status()
        data = await resp.json()
        return data.get("results", [])

    async def get_item(self, item_id: str) -> dict | None:
        resp = await self._client.get(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/__all__/issues/{item_id}"
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return await resp.json()

    async def update_state(self, item_id: str, state: str) -> None:
        resp = await self._client.patch(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/__all__/issues/{item_id}",
            json={"state": state},
        )
        resp.raise_for_status()

    async def add_comment(self, item_id: str, body: str) -> None:
        resp = await self._client.post(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/__all__/issues/{item_id}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
