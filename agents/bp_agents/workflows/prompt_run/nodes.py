import json
import logging
import os
import tempfile

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.agent_config import AgentConfig
from bp_agents.platform.dispatch import OUTCOME_FILENAME, DispatchContext, dispatch
from bp_agents.platform.sandbox import Sandbox, SandboxConfig
from bp_agents.workflows.prompt_run.state import PromptRunState

logger = logging.getLogger(__name__)


async def prompt_run_node(
    state: PromptRunState,
    sandbox: Sandbox,
    sandbox_config: SandboxConfig,
    skills_path: str,
    api_key: str,
    client: OpenCodeClient | None = None,
) -> dict:
    prompt = state["prompt"]
    outcome_path = os.path.join("/data/workspace", OUTCOME_FILENAME)

    wrapped_prompt = f"""{prompt}

When you finish, write a JSON result to $outcome_path.
Format: {{"result": "<summary>", "status": "success"}}"""

    with tempfile.TemporaryDirectory(prefix="prompt-run-") as workspace:
        config = AgentConfig(
            model=sandbox_config.env.get(
                "BP_MODEL", "openrouter/deepseek/deepseek-v4-flash"
            ),
            provider=sandbox_config.env.get("BP_PROVIDER", "openrouter"),
            permissions={
                "read": {"*": "allow"},
                "bash": {"*": "allow"},
                "edit": {"*": "allow"},
            },
            tools={},
            mcps={},
        )

        ctx = DispatchContext(
            opencode_client=client,
            broker=None,
            otel_port=None,
            mcp_port=None,
        )

        result = await dispatch(
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            config=config,
            skill="prompt-run",
            prompt=wrapped_prompt,
            workspace=workspace,
            outcome_path=outcome_path,
            api_key=api_key,
            ctx=ctx,
        )

        outcome_path_host = os.path.join(workspace, OUTCOME_FILENAME)
        try:
            with open(outcome_path_host) as f:
                outcome = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("failed to read outcome: %s", e)
            outcome = {"error": str(e), "status": "failed"}

        return {"outcome": outcome, "status": "done"}
