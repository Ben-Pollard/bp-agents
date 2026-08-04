from datetime import datetime

import httpx

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.contracts import Ticket, TicketState

# Default Redmine status ID to SDD TicketState mapping
# Redmine defaults: 1=New, 2=In Progress, 3=Resolved, 4=Feedback, 5=Closed, 6=Rejected
DEFAULT_STATUS_MAP: dict[str, int] = {
    "ready": 1,
    "implementing": 2,
    "awaiting_review": 3,
    "reviewing": 4,
    "awaiting_revision": 3,
    "revising": 2,
    "awaiting_verification": 3,
    "verifying": 4,
    "awaiting_approval": 3,
    "blocked": 6,
    "done": 5,
}

READY_STATUS_ID = 1


def _parse_issue(raw: dict, project: str) -> Ticket:
    status = raw.get("status", {})
    if isinstance(status, dict):
        status_name = str(status.get("name", ""))
    else:
        status_name = str(status or "")
    created = raw.get("created_on")
    updated = raw.get("updated_on")
    raw_description = raw.get("description")
    try:
        ticket_state = TicketState(status_name.lower())
    except ValueError:
        ticket_state = TicketState.READY
    return Ticket(
        id=str(raw["id"]),
        name=str(raw.get("subject", "")),
        description=str(raw_description) if raw_description is not None else None,
        state=ticket_state,
        project=project,
        labels=[],
        created_at=datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created and isinstance(created, str)
        else None,
        updated_at=datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if updated and isinstance(updated, str)
        else None,
    )


class RedmineTracker(Tracker):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        status_map: dict[str, int] | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self._status_map = status_map or DEFAULT_STATUS_MAP
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

    async def list_ready(self, project: str) -> list[Ticket]:
        resp = await self._client.get(
            "/issues.json",
            params={
                "project_id": project,
                "status_id": str(READY_STATUS_ID),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return [_parse_issue(item, project) for item in data.get("issues", [])]

    async def get_item(self, item_id: str, project: str) -> Ticket:
        resp = await self._client.get(f"/issues/{item_id}.json")
        resp.raise_for_status()
        data = resp.json()
        return _parse_issue(data.get("issue", {}), project)

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
