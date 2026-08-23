import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

WorkCallback = Callable[[dict, str], Awaitable[None]]

logger = logging.getLogger(__name__)


class WorkInitiator(ABC):
    @abstractmethod
    async def start(self, on_work: WorkCallback) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


class TrackerPoller(WorkInitiator):
    def __init__(
        self,
        tracker: Any,
        project: str,
        create_state: Callable[[dict], tuple[dict, str]],
        poll_interval: float = 5.0,
    ) -> None:
        self._tracker = tracker
        self._project = project
        self._create_state = create_state
        self._poll_interval = poll_interval
        self._stopped = False

    async def start(self, on_work: WorkCallback) -> None:
        while not self._stopped:
            try:
                tickets = await self._tracker.list_ready(self._project)
                for ticket in tickets:
                    state, thread_id = self._create_state(ticket)
                    await on_work(state, thread_id)
            except Exception:
                logger.exception("tracker poll error")
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._stopped = True
