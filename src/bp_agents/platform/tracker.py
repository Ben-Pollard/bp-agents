from abc import ABC, abstractmethod


class Tracker(ABC):
    @abstractmethod
    async def list_ready(self, project: str) -> list[dict]: ...

    @abstractmethod
    async def update_state(self, item_id: str, state: str, project: str) -> None: ...
