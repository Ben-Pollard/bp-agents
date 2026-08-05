import asyncio
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_fixed,
)

from bp_agents.platform.sandbox.egress import EgressPolicy
from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.graph import build_ticket_pipeline
from bp_agents.workflows.sdd.state import initial_ticket_state
from bp_agents.workflows.sdd.tracker import RedmineTracker

logger = logging.getLogger(__name__)

_ENV_PATH = "/data/env/.env"

load_dotenv(dotenv_path=_ENV_PATH)

EGRESS_PROXY_URL = os.getenv("EGRESS_PROXY_URL", "http://egress-proxy:8080")
REDMINE_BASE_URL = os.getenv("REDMINE_BASE_URL", "http://redmine:3000")
POLL_INTERVAL = int(os.getenv("BP_POLL_INTERVAL", "5"))
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY", "")
REDMINE_PROJECT = os.getenv("REDMINE_PROJECT", "default")
PIPELINE_DB_PATH = os.getenv("BP_PIPELINE_DB_PATH", "pipeline_checkpoints.db")


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


async def _poll_loop(tracker: Tracker, pipeline: Any) -> None:
    while True:
        try:
            ready = await tracker.list_ready(REDMINE_PROJECT)
            logger.info(
                "ticket discovery: %d ready  project=%s",
                len(ready),
                REDMINE_PROJECT,
            )
            for ticket in ready:
                state = initial_ticket_state(ticket["id"], REDMINE_PROJECT)
                config = {
                    "configurable": {"thread_id": ticket["id"]},
                }
                await pipeline.ainvoke(state, config)
        except Exception:
            logger.exception("ticket discovery failed")
        await asyncio.sleep(POLL_INTERVAL)


async def main_async(tracker: Tracker | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logger.info("orchestrator starting...")

    egress_policy = EgressPolicy()
    logger.info(
        "egress allowlist on startup: %s",
        egress_policy.allowlist,
    )

    wait_for_dependency(f"{REDMINE_BASE_URL}/", "Redmine")
    wait_for_dependency(f"{EGRESS_PROXY_URL}/", "egress-proxy")

    if tracker is None:
        tracker = RedmineTracker(
            base_url=REDMINE_BASE_URL,
            api_key=REDMINE_API_KEY,
        )
        await tracker.ensure_statuses()

    logger.info("orchestrator ready")

    async with AsyncSqliteSaver.from_conn_string(PIPELINE_DB_PATH) as checkpointer:
        pipeline = build_ticket_pipeline(checkpointer=checkpointer, tracker=tracker)
        await _poll_loop(tracker, pipeline)


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("orchestrator shutting down")


if __name__ == "__main__":
    main()
