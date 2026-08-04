from datetime import datetime

import httpx

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import Ticket


def _parse_ticket(raw: dict, project: str) -> Ticket:
    labels = raw.get("labels") or []
    if isinstance(labels, list):
        label_names: list[str] = []
        for lbl in labels:
            if isinstance(lbl, dict):
                label_names.append(lbl.get("name", str(lbl)))
            else:
                label_names.append(str(lbl))
    else:
        label_names = [str(labels)] if labels else []
    state = raw.get("state")
    if isinstance(state, dict):
        state_str = str(state.get("name", ""))
    else:
        state_str = str(state or "")
    created = raw.get("created_at")
    updated = raw.get("updated_at")
    return Ticket(
        id=str(raw["id"]),
        name=str(raw.get("name", "")),
        description=str(raw.get("description_html", "") or ""),
        state=state_str,
        project=project,
        labels=label_names,
        created_at=datetime.fromisoformat(created)
        if created and isinstance(created, str)
        else None,
        updated_at=datetime.fromisoformat(updated)
        if updated and isinstance(updated, str)
        else None,
    )


class PlaneTracker(Tracker):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace_slug: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.workspace_slug = workspace_slug
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "X-API-Key": api_key,
                    "Content-Type": "application/json",
                },
                follow_redirects=True,
            )

    async def list_ready(self, project: str) -> list[Ticket]:
        resp = await self._client.get(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/",
            params={"state_group": "backlog"},
        )
        resp.raise_for_status()
        data = resp.json()
        return [_parse_ticket(item, project) for item in data.get("results", [])]

    async def get_item(self, item_id: str, project: str) -> Ticket:
        resp = await self._client.get(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/{item_id}/",
        )
        resp.raise_for_status()
        return _parse_ticket(resp.json(), project)

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        resp = await self._client.patch(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/{item_id}/",
            json={"state": state},
        )
        resp.raise_for_status()

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        resp = await self._client.post(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/{item_id}/comments/",
            json={"comment_body": body},
        )
        resp.raise_for_status()
