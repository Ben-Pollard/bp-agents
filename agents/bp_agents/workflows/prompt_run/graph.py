from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.sandbox import Sandbox, SandboxConfig
from bp_agents.workflows.prompt_run.nodes import prompt_run_node
from bp_agents.workflows.prompt_run.state import PromptRunState


def build_prompt_run_pipeline(
    checkpointer: AsyncSqliteSaver | None = None,
    sandbox: Sandbox | None = None,
    sandbox_config: SandboxConfig | None = None,
    skills_path: str | None = None,
    client: OpenCodeClient | None = None,
    api_key: str | None = None,
):
    builder = StateGraph(PromptRunState)

    async def run_node(state: PromptRunState) -> dict:
        return await prompt_run_node(
            state=state,
            sandbox=sandbox,
            sandbox_config=sandbox_config,
            skills_path=skills_path or "",
            api_key=api_key or "",
            client=client,
        )

    builder.add_node("run", run_node)
    builder.add_edge(START, "run")
    builder.add_edge("run", END)

    return builder.compile(checkpointer=checkpointer)
