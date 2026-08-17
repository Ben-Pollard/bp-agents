import asyncio
import json
import logging
import os
import secrets
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.agent_config import AgentConfig, to_opencode_json
from bp_agents.platform.mcp.contract_broker import ContractNotFulfilledError
from bp_agents.platform.sandbox.base import Sandbox
from bp_agents.platform.sandbox.config import SandboxConfig

if TYPE_CHECKING:
    from bp_agents.platform.mcp.contract_broker import ContractBroker

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
                "limit": {"context": 131072, "output": 65536},
            },
        },
    },
}


OUTCOME_FILENAME = "outcome.json"
HEALTH_CHECK_RETRIES = 30
HEALTH_CHECK_INTERVAL = 1.0


async def _stream_container_logs(
    container_id: str,
    log: logging.Logger,
) -> asyncio.Task:
    """Tail sandbox container logs to orchestrator stdout."""

    async def _stream() -> None:
        try:
            import docker

            client = docker.from_env()
            container = client.containers.get(container_id)

            def _read_logs() -> None:
                for line in container.logs(
                    stdout=True,
                    stderr=True,
                    stream=True,
                    follow=True,
                    timestamps=True,
                ):
                    text = line.decode(errors="replace").rstrip()
                    log.info("[sandbox] %s", text)

            await asyncio.to_thread(_read_logs)
        except Exception:
            log.debug("sandbox log stream ended for %s", container_id)

    return asyncio.create_task(_stream())


async def _wait_for_health(
    base_url: str, max_retries: int = HEALTH_CHECK_RETRIES
) -> bool:
    async with httpx.AsyncClient(base_url=base_url) as client:

        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_fixed(HEALTH_CHECK_INTERVAL),
            retry=retry_if_exception_type((httpx.HTTPError, RuntimeError)),
            reraise=False,
        )
        async def _probe() -> None:
            resp = await client.get("/api/health", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("healthy"):
                raise RuntimeError(f"unhealthy: {resp.text[:500]}")

        try:
            await _probe()
            return True
        except RetryError:
            return False


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
    broker: "ContractBroker | None" = None,
    otel_port: int | None = None,
    mcp_port: int | None = None,
) -> dict:
    """Full agent lifecycle.

    1. Write opencode.json to workspace root
    2. Create container (skills and workspace bind-mounted)
    3. Wait for GET /api/health → {"healthy": true}
    4. PUT /auth/{provider} inject creds
    5. POST /session create session
    6. POST /session/{id}/message send prompt (blocks until agent done via polling)
    7. Read outcome_path from workspace, validate against stage contract
    8. Destroy container
    Returns validated outcome dict. Raises on failure — container always destroyed.
    """
    if not api_key:
        raise RuntimeError(
            f"dispatch: {config.provider} api_key is empty — set {config.provider.upper()}_API_KEY in environment"
        )

    skills_path = sandbox_config.skills_path
    if not skills_path or not Path(skills_path).is_dir():
        raise RuntimeError(
            f"dispatch: skills_path {skills_path!r} is not a directory — "
            f"skills must be mounted before dispatch"
        )
    skill_dirs = list(Path(skills_path).iterdir())
    has_skill_md = any((p / "SKILL.md").is_file() for p in skill_dirs if p.is_dir())
    if not has_skill_md:
        raise RuntimeError(
            f"dispatch: no SKILL.md found under {skills_path} — "
            f"skill directories must contain a SKILL.md file. "
            f"contents: {[p.name for p in skill_dirs]}"
        )

    mcp_defs: dict = {}
    if broker is not None and mcp_port is not None:
        mcp_defs["contract-broker"] = {
            "type": "remote",
            "url": f"http://orchestrator:{mcp_port}/mcp",
        }

    opencode_config = to_opencode_json(
        config,
        PROVIDER_DEFINITIONS,
        mcp_defs,
        skills_path=skills_path,
        otel_enabled=otel_port is not None,
        plugins=["otel-observability.ts"],
    )
    opencode_path = os.path.join(workspace, "opencode.json")
    with open(opencode_path, "w") as f:
        json.dump(opencode_config, f, indent=2)
    logger.debug("wrote %s config=%s", opencode_path, json.dumps(opencode_config))

    # Copy OTEL plugin to workspace so opencode can load it
    _plugin_src = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        ".agents",
        "plugins",
        "otel-observability.ts",
    )
    _plugin_dst = os.path.join(workspace, "otel-observability.ts")
    if os.path.exists(_plugin_src):
        shutil.copy2(_plugin_src, _plugin_dst)
        logger.debug("copied OTEL plugin to %s", _plugin_dst)

    broker_token: str | None = None
    if broker is not None:
        run_id = secrets.token_urlsafe(16)
        broker_token = broker.create_binding("sdd", skill, run_id, max_attempts=3)

    env = {
        **{k: v for k, v in sandbox_config.env.items() if k not in CREDENTIAL_KEYS},
        "outcome_path": outcome_path,
    }
    if otel_port is not None:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"http://orchestrator:{otel_port}"
    if broker_token is not None:
        env["CONTRACT_BROKER_TOKEN"] = broker_token

    logger.debug("dispatch: building SandboxConfig with image=%s", sandbox_config.image)

    cfg = SandboxConfig(
        image=sandbox_config.image,
        workspace_path=workspace,
        skills_path=sandbox_config.skills_path,
        runtime=sandbox_config.runtime,
        workspace_mode="rw",
        env=env,
        timeout_seconds=sandbox_config.timeout_seconds,
        mem_limit=sandbox_config.mem_limit,
        cpu_count=sandbox_config.cpu_count,
        network=sandbox_config.network,
        http_proxy=sandbox_config.http_proxy,
        https_proxy=sandbox_config.https_proxy,
        no_proxy=sandbox_config.no_proxy,
        dns_servers=sandbox_config.dns_servers,
        extra_hosts=sandbox_config.extra_hosts,
        command=sandbox_config.command,
    )

    logger.debug(
        "dispatch: sandbox config built, calling create with network=%s runtime=%s",
        cfg.network,
        cfg.runtime,
    )

    sandbox_session = await sandbox.create(cfg)
    log_stream = await _stream_container_logs(sandbox_session.container_id, logger)
    logger.debug(
        "sandbox create returned: session=%s base_url=%s",
        sandbox_session.container_id,
        sandbox_session.base_url,
    )
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

        outcome_host_path = os.path.join(workspace, OUTCOME_FILENAME)

        if broker is not None and broker_token is not None:
            accepted = broker.check_acceptance(broker_token)
            if accepted is not None:
                logger.debug("broker accepted contract for token=%s", broker_token[:8])
                return accepted.contract
            status = broker.submission_status(broker_token)
            if status == "exhausted":
                raise ContractNotFulfilledError(
                    "agent: contract validation failed - max attempts exceeded"
                )
            if status == "pending":
                raise ContractNotFulfilledError("agent: no contract submitted via MCP")
            raise ContractNotFulfilledError(
                "agent: contract binding expired or invalid"
            )

        logger.debug("looking for outcome at %s", outcome_host_path)
        if not os.path.exists(outcome_host_path):
            logger.debug(
                "outcome file NOT FOUND at %s (cwd=%s dir=%s)",
                outcome_host_path,
                os.getcwd(),
                os.listdir(workspace) if os.path.isdir(workspace) else "not-a-dir",
            )
            raise FileNotFoundError(f"Outcome file not found at {outcome_host_path}")
        with open(outcome_host_path) as f:
            outcome = json.load(f)
            logger.debug("read outcome: %s", json.dumps(outcome))

        return outcome
    finally:
        if log_stream is not None:
            log_stream.cancel()
            try:
                await log_stream
            except (asyncio.CancelledError, Exception):
                pass
        if oc_session is not None:
            try:
                await client.abort(oc_session)
            except (httpx.ClosedResourceError, httpx.ConnectError, RuntimeError):
                logger.warning("abort failed during cleanup (client may be closed)")
            except Exception:
                logger.exception("abort failed during cleanup")
        if own_client:
            await client.close()
        await sandbox.destroy(sandbox_session.container_id)
