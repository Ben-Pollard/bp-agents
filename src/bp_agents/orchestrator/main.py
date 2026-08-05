import asyncio
import logging
import os
import time
from typing import Any

import httpx
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.graph import build_ticket_pipeline
from bp_agents.workflows.sdd.state import TicketPipelineState
from bp_agents.workflows.sdd.tracker import RedmineTracker

logger = logging.getLogger(__name__)

_ENV_PATH = "/data/env/.env"


def _load_env_file() -> None:
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env_file()

EGRESS_PROXY_URL = os.getenv("EGRESS_PROXY_URL", "http://egress-proxy:8080")
REDMINE_BASE_URL = os.getenv("REDMINE_BASE_URL", "http://redmine:3000")
POLL_INTERVAL = int(os.getenv("BP_POLL_INTERVAL", "5"))
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY", "")
REDMINE_PROJECT = os.getenv("REDMINE_PROJECT", "default")
PIPELINE_DB_PATH = os.getenv("BP_PIPELINE_DB_PATH", "pipeline_checkpoints.db")


def wait_for_dependency(url: str, name: str, timeout: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            logger.info("%s responded with status %s", name, r.status_code)
            return
        except httpx.HTTPError:
            logger.debug("%s not ready yet, retrying...", name)
        time.sleep(1)
    raise RuntimeError("%s did not become ready within %ds" % (name, timeout))


def _to_pipeline_state(ticket: dict, project: str) -> TicketPipelineState:
    return {
        "ticket_id": ticket["id"],
        "project": project,
        "status": "ready",
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
        "review_approved": None,
        "verification_passed": None,
        "blocked_reason": None,
    }


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
                state = _to_pipeline_state(ticket, REDMINE_PROJECT)
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
