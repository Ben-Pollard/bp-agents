import asyncio
import logging
import os
import time

import httpx

from bp_agents.workflows.sdd.tracker import PlaneTracker

logger = logging.getLogger(__name__)

EGRESS_PROXY_URL = os.getenv("EGRESS_PROXY_URL", "http://egress-proxy:8081")
PLANE_BASE_URL = os.getenv("PLANE_BASE_URL", "http://plane:80")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
POLL_INTERVAL = int(os.getenv("BP_POLL_INTERVAL", "5"))
PLANE_API_KEY = os.getenv("PLANE_API_KEY", "")
PLANE_WORKSPACE_SLUG = os.getenv("PLANE_WORKSPACE_SLUG", "")
PLANE_PROJECT = os.getenv("PLANE_PROJECT", "default")


def wait_for_dependency(url: str, name: str, timeout: int = 120) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            logger.info("%s responded with status %s", name, r.status_code)
            return
        except httpx.ConnectError:
            logger.debug("%s not ready yet, retrying...", name)
            time.sleep(1)
    raise RuntimeError("%s did not become ready within %ds" % (name, timeout))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logger.info("orchestrator starting...")

    wait_for_dependency(f"{PLANE_BASE_URL}/api/v1", "Plane")
    wait_for_dependency(LANGFUSE_HOST, "Langfuse")
    wait_for_dependency(f"{EGRESS_PROXY_URL}/", "egress-proxy")

    tracker = PlaneTracker(
        base_url=PLANE_BASE_URL,
        api_key=PLANE_API_KEY,
        workspace_slug=PLANE_WORKSPACE_SLUG,
    )

    logger.info("orchestrator ready")

    try:
        while True:
            ready = asyncio.run(tracker.list_ready(PLANE_PROJECT))
            logger.info(
                "ticket discovery: %d ready  project=%s", len(ready), PLANE_PROJECT
            )
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        logger.info("orchestrator shutting down")


if __name__ == "__main__":
    main()
