import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from bp_agents.platform.dispatch import CREDENTIAL_KEYS
from bp_agents.platform.runner import setup_logging
from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.workflows.prompt_run.graph import build_prompt_run_pipeline
from bp_agents.workflows.prompt_run.state import PromptRunState

logger = logging.getLogger(__name__)


def _sandbox_net_ips() -> dict[str, str]:
    import docker

    result = {}
    client = docker.from_env()
    for service in ("orchestrator", "egress-proxy"):
        filters = {"label": f"com.docker.compose.service={service}"}
        containers = client.containers.list(filters=filters)
        if containers:
            nets = containers[0].attrs["NetworkSettings"]["Networks"]
            if "sandbox_net" in nets:
                result[service] = nets["sandbox_net"]["IPAddress"]
    return result


async def main() -> None:
    setup_logging()
    load_dotenv()

    prompt = os.getenv("BP_PROMPT")
    if not prompt:
        logger.error("BP_PROMPT env var is required")
        return

    sandbox_env = {}
    for key in CREDENTIAL_KEYS:
        val = os.getenv(key)
        if val:
            sandbox_env[key] = val

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASEURL"):
        val = os.getenv(key)
        if val:
            sandbox_env[key] = val

    sandbox_image = os.getenv("BP_SANDBOX_IMAGE", "opencode-agent:latest")
    runtime = "runsc"
    api_key = sandbox_env.get("OPENROUTER_API_KEY", "")

    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    skills_path = os.path.join(
        project_root, "src", "bp_agents", "workflows", "prompt_run", "skills"
    )
    skills_path = os.path.abspath(skills_path)

    sandbox = DockerSandbox()

    sandbox_config = SandboxConfig(
        image=sandbox_image,
        workspace_path="/tmp/prompt-run-workspace",
        skills_path=skills_path,
        runtime=runtime,
        network="sandbox_net",
        http_proxy="http://egress-proxy:8080",
        https_proxy="http://egress-proxy:8080",
        dns_servers=["8.8.8.8"],
        extra_hosts=_sandbox_net_ips(),
        env=sandbox_env,
        command=[
            "opencode",
            "serve",
            "--port",
            "8080",
            "--print-logs",
            "--hostname",
            "0.0.0.0",
        ],
    )

    async with AsyncSqliteSaver.from_conn_string(
        "prompt_run_checkpoints.db"
    ) as checkpointer:
        pipeline = build_prompt_run_pipeline(
            checkpointer=checkpointer,
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            skills_path=skills_path,
            api_key=api_key,
        )

        state: PromptRunState = {
            "prompt": prompt,
            "status": "running",
            "outcome": None,
        }

        result = await pipeline.ainvoke(
            state, {"configurable": {"thread_id": "prompt-run-01"}}
        )
        print("=== Outcome ===")
        print(json.dumps(result.get("outcome", {}), indent=2))
        print(f"Status: {result.get('status', 'unknown')}")


if __name__ == "__main__":
    asyncio.run(main())
