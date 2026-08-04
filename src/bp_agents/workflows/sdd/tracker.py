import httpx

from bp_agents.platform.tracker import Tracker


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

    async def list_ready(self, project: str) -> list[dict]:
        resp = await self._client.get(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/",
            params={"state_group": "backlog"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        resp = await self._client.patch(
            f"/api/v1/workspaces/{self.workspace_slug}/projects/{project}/issues/{item_id}/",
            json={"state": state},
        )
        resp.raise_for_status()
