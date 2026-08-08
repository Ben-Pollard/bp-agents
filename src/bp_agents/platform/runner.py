import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_fixed,
)

from bp_agents.platform.work_initiator import WorkInitiator

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s")


def wait_for_dependency(url: str, name: str, timeout: int = 120) -> None:
    @retry(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=False,
    )
    def _probe() -> None:
        r = httpx.get(url, timeout=5)
        logger.info("%s responded with status %s", name, r.status_code)

    try:
        _probe()
    except RetryError:
        raise RuntimeError("%s did not become ready within %ds" % (name, timeout))


@dataclass
class _Binding:
    name: str
    graph: Any
    initiator: WorkInitiator


class GraphRunner:
    def __init__(self) -> None:
        self._bindings: list[_Binding] = []

    def register(self, name: str, graph: Any, initiator: WorkInitiator) -> None:
        self._bindings.append(_Binding(name=name, graph=graph, initiator=initiator))

    async def start(self) -> None:
        setup_logging()
        logger.info(
            "runner starting...  graphs=%s",
            [b.name for b in self._bindings],
        )

        tasks: list[asyncio.Task[None]] = []
        for binding in self._bindings:
            g = binding.graph

            async def on_work(state: dict, thread_id: str) -> None:
                config = {"configurable": {"thread_id": thread_id}}
                await g.ainvoke(state, config)

            task = asyncio.create_task(binding.initiator.start(on_work))
            tasks.append(task)

        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("shutting down")
            for binding in self._bindings:
                await binding.initiator.stop()
            for task in tasks:
                task.cancel()
