import asyncio
import logging
import os

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from bp_agents.platform.dispatch import CREDENTIAL_KEYS
from bp_agents.platform.mcp.contract_broker import (
    ContractBroker,
    create_mcp_server,
)
from bp_agents.platform.observability.otel_receiver import OtelReceiver
from bp_agents.platform.runner import GraphRunner, setup_logging, wait_for_dependency
from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.platform.sandbox.egress import EgressPolicy
from bp_agents.platform.work_initiator import TrackerPoller
from bp_agents.workflows.sdd.contracts import ReviewOutput, RevisionOutput, TddOutput
from bp_agents.workflows.sdd.graph import build_ticket_pipeline
from bp_agents.workflows.sdd.state import initial_ticket_state
from bp_agents.workflows.sdd.tracker import RedmineTracker

_ENV_PATH = "/data/env/.env"
load_dotenv(dotenv_path=_ENV_PATH)

logger = logging.getLogger(__name__)

REDMINE_BASE_URL = os.getenv("REDMINE_BASE_URL", "http://redmine:3000")
REDMINE_API_KEY = os.getenv("REDMINE_API_KEY", "")
REDMINE_PROJECT = os.getenv("REDMINE_PROJECT", "default")
POLL_INTERVAL = int(os.getenv("BP_POLL_INTERVAL", "5"))
PIPELINE_DB_PATH = os.getenv("BP_PIPELINE_DB_PATH", "pipeline_checkpoints.db")
SANDBOX_IMAGE = os.getenv("BP_SANDBOX_IMAGE", "symphony-agent:latest")
TARGET_REPO_PATH = os.getenv("BP_TARGET_REPO_PATH", "")
SKILLS_PATH = os.getenv("BP_SKILLS_PATH", ".agents/skills")
SANDBOX_RUNTIME = os.getenv("BP_SANDBOX_RUNTIME", "runsc")
MCP_PORT = int(os.getenv("BP_MCP_PORT", "8001"))
BP_LOG_LEVEL = os.getenv("BP_LOG_LEVEL", "info")
BP_OTEL_PORT = int(os.getenv("BP_OTEL_PORT", "4318"))


def _build_sdd_state(ticket: dict) -> tuple[dict, str]:
    state = initial_ticket_state(
        ticket["id"],
        REDMINE_PROJECT,
        ticket.get("description") or "",
    )
    return state, ticket["id"]


async def main() -> None:
    setup_logging()
    logger.info("sdd orchestrator starting")

    egress_policy = EgressPolicy()
    logger.info("egress allowlist on startup: %s", egress_policy.allowlist)

    wait_for_dependency(f"{REDMINE_BASE_URL}/", "Redmine")

    tracker = RedmineTracker(
        base_url=REDMINE_BASE_URL,
        api_key=REDMINE_API_KEY,
    )
    await tracker.ensure_statuses()

    sandbox = None
    sandbox_config = None
    if TARGET_REPO_PATH:
        sandbox = DockerSandbox(egress_policy=egress_policy)
        sandbox_env = {}
        for key in CREDENTIAL_KEYS:
            val = os.getenv(key)
            if val:
                sandbox_env[key] = val

        sandbox_config = SandboxConfig(
            image=SANDBOX_IMAGE,
            workspace_path=TARGET_REPO_PATH,
            skills_path=os.path.abspath(SKILLS_PATH)
            if not os.path.isabs(SKILLS_PATH)
            else SKILLS_PATH,
            runtime=SANDBOX_RUNTIME,
            network="bp_agents",
            http_proxy="http://172.20.0.10:8080",
            https_proxy="http://172.20.0.10:8080",
            dns_servers=["8.8.8.8"],
            env=sandbox_env,
            command=["opencode", "serve", "--port", "8080", "--hostname", "0.0.0.0"],
        )

    async with AsyncSqliteSaver.from_conn_string(PIPELINE_DB_PATH) as checkpointer:
        pipeline = build_ticket_pipeline(
            checkpointer=checkpointer,
            tracker=tracker,
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=TARGET_REPO_PATH,
            skills_path=os.path.abspath(SKILLS_PATH)
            if not os.path.isabs(SKILLS_PATH)
            else SKILLS_PATH,
            otel_port=BP_OTEL_PORT if sandbox_config is not None else None,
        )

        poller = TrackerPoller(
            tracker, REDMINE_PROJECT, _build_sdd_state, POLL_INTERVAL
        )
        runner = GraphRunner()
        runner.register("sdd", pipeline, poller)

        broker = ContractBroker()
        broker.register("sdd", "tdd", TddOutput)
        broker.register("sdd", "code_review", ReviewOutput)
        broker.register("sdd", "revision", RevisionOutput)
        mcp = create_mcp_server(broker)

        otel_receiver = OtelReceiver(log_level=BP_LOG_LEVEL)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                mcp.run_streamable_http_async(
                    host="127.0.0.1",
                    port=MCP_PORT,
                    json_response=True,
                    stateless_http=True,
                )
            )
            await otel_receiver.start(port=BP_OTEL_PORT)
            await runner.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("sdd orchestrator shutting down")
