import httpx

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import TicketState


class RedmineTracker(Tracker):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self._status_map: dict[str, int] = {}
        self._reverse_map: dict[int, str] = {}
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "X-Redmine-API-Key": api_key,
                    "Content-Type": "application/json",
                },
            )

    async def ensure_statuses(self) -> None:
        resp = await self._client.get("/issue_statuses.json")
        resp.raise_for_status()
        data = resp.json()
        existing = {s["name"]: s for s in data.get("issue_statuses", [])}

        for state in TicketState:
            name = state.value
            if name not in existing:
                is_closed = name in ("done", "blocked")
                post_resp = await self._client.post(
                    "/issue_statuses.json",
                    json={"issue_status": {"name": name, "is_closed": is_closed}},
                )
                post_resp.raise_for_status()
                created = post_resp.json().get("issue_status", {})
                existing[name] = created

        self._status_map = {
            name: s["id"]
            for name, s in existing.items()
            if name in TicketState._value2member_map_
        }
        self._reverse_map = {v: k for k, v in self._status_map.items()}

    def _parse_issue(self, raw: dict, project: str) -> dict:
        status = raw.get("status", {})
        if isinstance(status, dict):
            status_id = status.get("id")
        else:
            status_id = None
        ticket_state = TicketState(
            self._reverse_map.get(status_id, TicketState.READY.value)
        )
        created = raw.get("created_on")
        updated = raw.get("updated_on")
        raw_description = raw.get("description")
        return {
            "id": str(raw["id"]),
            "name": str(raw.get("subject", "")),
            "description": str(raw_description)
            if raw_description is not None
            else None,
            "state": ticket_state.value,
            "project": project,
            "labels": [],
            "created_at": created if created else None,
            "updated_at": updated if updated else None,
        }

    async def list_ready(self, project: str) -> list[dict]:
        ready_id = self._status_map.get(TicketState.READY.value)
        if ready_id is None:
            return []
        resp = await self._client.get(
            "/issues.json",
            params={
                "project_id": project,
                "status_id": str(ready_id),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_issue(item, project) for item in data.get("issues", [])]

    async def get_item(self, item_id: str, project: str) -> dict:
        resp = await self._client.get(f"/issues/{item_id}.json")
        resp.raise_for_status()
        data = resp.json()
        return self._parse_issue(data.get("issue", {}), project)

    async def update_state(self, item_id: str, state: str, project: str) -> None:
        status_id = self._status_map.get(state)
        if status_id is None:
            msg = f"Unknown SDD state: {state}"
            raise ValueError(msg)
        resp = await self._client.put(
            f"/issues/{item_id}.json",
            json={"issue": {"status_id": status_id}},
        )
        resp.raise_for_status()

    async def add_comment(self, item_id: str, body: str, project: str) -> None:
        resp = await self._client.put(
            f"/issues/{item_id}.json",
            json={"issue": {"notes": body}},
        )
        resp.raise_for_status()
