import asyncio
import json
import logging
import os

import httpx

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.agent_config import AgentConfig, to_opencode_json
from bp_agents.platform.sandbox.base import Sandbox
from bp_agents.platform.sandbox.config import SandboxConfig

CREDENTIAL_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
}

logger = logging.getLogger(__name__)

PROVIDER_DEFINITIONS: dict = {
    "openrouter": {
        "name": "OpenRouter",
        "api": "https://openrouter.ai/api/v1",
        "models": {
            "deepseek/deepseek-v4-flash": {
                "name": "DeepSeek V4 Flash",
                "limit": {"context": 131072},
            },
        },
    },
}

MCP_DEFS: dict = {}

OUTCOME_FILENAME = "outcome.json"
HEALTH_CHECK_RETRIES = 30
HEALTH_CHECK_INTERVAL = 1.0
SESSION_POLL_INTERVAL = 2.0
SESSION_TIMEOUT = 600


async def _wait_for_health(
    base_url: str, max_retries: int = HEALTH_CHECK_RETRIES
) -> bool:
    async with httpx.AsyncClient(base_url=base_url) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.get("/api/health", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("healthy") is True:
                        return True
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
    return False


async def _wait_for_session_completion(
    client: OpenCodeClient,
    session,
    timeout: float = SESSION_TIMEOUT,
) -> dict:
    elapsed = 0.0
    while elapsed < timeout:
        status = await client.session_status(session)
        state = status.get("state", "running")
        if state != "running":
            return status
        await asyncio.sleep(SESSION_POLL_INTERVAL)
        elapsed += SESSION_POLL_INTERVAL
    raise TimeoutError(
        f"session {session.session_id} did not complete within {timeout}s"
    )


async def dispatch(
    sandbox: Sandbox,
    sandbox_config: SandboxConfig,
    config: AgentConfig,
    skill: str,
    prompt: str,
    workspace: str,
    outcome_path: str,
    api_key: str,
    opencode_client: OpenCodeClient | None = None,
) -> dict:
    """Full agent lifecycle.

    1. Write opencode.json to workspace root
    2. Create container (skills and workspace bind-mounted)
    3. Wait for GET /api/health → {"healthy": true}
    4. PUT /auth/{provider} inject creds
    5. POST /session create session
    6. POST /session/{id}/message send prompt (blocks until agent done)
    7. Read outcome_path from workspace, validate against stage contract
    8. Destroy container
    Returns validated outcome dict. Raises on failure — container always destroyed.
    """
    opencode_config = to_opencode_json(config, PROVIDER_DEFINITIONS, MCP_DEFS)
    opencode_path = os.path.join(workspace, "opencode.json")
    with open(opencode_path, "w") as f:
        json.dump(opencode_config, f, indent=2)

    cfg = SandboxConfig(
        image=sandbox_config.image,
        workspace_path=workspace,
        skills_path=sandbox_config.skills_path,
        runtime=sandbox_config.runtime,
        workspace_mode="rw",
        env={
            **{k: v for k, v in sandbox_config.env.items() if k not in CREDENTIAL_KEYS},
            "outcome_path": outcome_path,
        },
        timeout_seconds=sandbox_config.timeout_seconds,
        mem_limit=sandbox_config.mem_limit,
        cpu_count=sandbox_config.cpu_count,
        network=sandbox_config.network,
        http_proxy=sandbox_config.http_proxy,
        https_proxy=sandbox_config.https_proxy,
        no_proxy=sandbox_config.no_proxy,
        dns_servers=sandbox_config.dns_servers,
        command=sandbox_config.command,
    )

    sandbox_session = await sandbox.create(cfg)
    own_client = opencode_client is None
    client = opencode_client or OpenCodeClient(sandbox_session.base_url)
    oc_session = None

    try:
        healthy = await _wait_for_health(sandbox_session.base_url)
        if not healthy:
            raise RuntimeError(
                f"Sandbox at {sandbox_session.base_url} did not become healthy"
            )

        await client.auth_set(config.provider, api_key)

        oc_session = await client.create_session()

        provider_id = config.provider
        model_id = (
            config.model.split("/", 1)[1] if "/" in config.model else config.model
        )

        await client.send_message(
            oc_session,
            [{"type": "text", "text": prompt}],
            (provider_id, model_id),
            config.tools,
        )

        await _wait_for_session_completion(client, oc_session)

        outcome_host_path = os.path.join(workspace, OUTCOME_FILENAME)
        if not os.path.exists(outcome_host_path):
            raise FileNotFoundError(f"Outcome file not found at {outcome_host_path}")
        with open(outcome_host_path) as f:
            outcome = json.load(f)

        return outcome
    finally:
        if own_client:
            await client.close()
        if oc_session is not None:
            await client.abort(oc_session)
        await sandbox.destroy(sandbox_session.container_id)
