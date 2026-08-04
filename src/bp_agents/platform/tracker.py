from abc import ABC, abstractmethod

from bp_agents.workflows.sdd.contracts import Ticket


class Tracker(ABC):
    @abstractmethod
    async def list_ready(self, project: str) -> list[Ticket]: ...

    @abstractmethod
    async def get_item(self, item_id: str, project: str) -> Ticket: ...

    @abstractmethod
    async def update_state(self, item_id: str, state: str, project: str) -> None: ...

    @abstractmethod
    async def add_comment(self, item_id: str, body: str, project: str) -> None: ...
