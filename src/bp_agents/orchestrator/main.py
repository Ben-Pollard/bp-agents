import asyncio
import logging
import os
import time

import httpx
from langgraph.checkpoint.sqlite import SqliteSaver

from bp_agents.platform.tracker import Tracker
from bp_agents.workflows.sdd.graph import build_ticket_pipeline
from bp_agents.workflows.sdd.state import TicketPipelineState
from bp_agents.workflows.sdd.tracker import PlaneTracker

logger = logging.getLogger(__name__)

EGRESS_PROXY_URL = os.getenv("EGRESS_PROXY_URL", "http://egress-proxy:8081")
PLANE_BASE_URL = os.getenv("PLANE_BASE_URL", "http://plane:80")
POLL_INTERVAL = int(os.getenv("BP_POLL_INTERVAL", "5"))
PLANE_API_KEY = os.getenv("PLANE_API_KEY", "")
PLANE_WORKSPACE_SLUG = os.getenv("PLANE_WORKSPACE_SLUG", "")
PLANE_PROJECT = os.getenv("PLANE_PROJECT", "default")
PIPELINE_DB_PATH = os.getenv("BP_PIPELINE_DB_PATH", "pipeline_checkpoints.db")


def wait_for_dependency(url: str, name: str, timeout: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                logger.info("%s responded with status %s", name, r.status_code)
                return
            logger.debug("%s returned status %s, retrying...", name, r.status_code)
        except httpx.HTTPError:
            logger.debug("%s not ready yet, retrying...", name)
        time.sleep(1)
    raise RuntimeError("%s did not become ready within %ds" % (name, timeout))


def _to_pipeline_state(ticket, project: str) -> TicketPipelineState:
    return {
        "ticket_id": ticket.id,
        "project": project,
        "status": "implementing",
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
    }


def main(tracker: Tracker | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logger.info("orchestrator starting...")

    wait_for_dependency(f"{PLANE_BASE_URL}/api/v1", "Plane")
    wait_for_dependency(f"{EGRESS_PROXY_URL}/", "egress-proxy")

    if tracker is None:
        tracker = PlaneTracker(
            base_url=PLANE_BASE_URL,
            api_key=PLANE_API_KEY,
            workspace_slug=PLANE_WORKSPACE_SLUG,
        )

    logger.info("orchestrator ready")

    with SqliteSaver.from_conn_string(PIPELINE_DB_PATH) as checkpointer:
        pipeline = build_ticket_pipeline(checkpointer=checkpointer)

        try:
            while True:
                try:
                    ready = asyncio.run(tracker.list_ready(PLANE_PROJECT))
                    logger.info(
                        "ticket discovery: %d ready  project=%s",
                        len(ready),
                        PLANE_PROJECT,
                    )
                    for ticket in ready:
                        state = _to_pipeline_state(ticket, PLANE_PROJECT)
                        config = {
                            "configurable": {"thread_id": ticket.id},
                        }
                        pipeline.invoke(state, config)
                except Exception:
                    logger.exception("ticket discovery failed")
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("orchestrator shutting down")


if __name__ == "__main__":
    main()
