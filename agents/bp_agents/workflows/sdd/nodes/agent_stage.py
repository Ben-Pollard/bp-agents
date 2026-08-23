import asyncio
import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.dispatch import OUTCOME_FILENAME, DispatchContext, dispatch
from bp_agents.platform.mcp.contract_broker import ContractNotFulfilledError
from bp_agents.platform.sandbox import Sandbox, SandboxConfig
from bp_agents.platform.sandbox.config import WORKSPACE_MOUNT_PATH
from bp_agents.workflows.sdd.skill_configs import SKILL_CONFIGS
from bp_agents.workflows.sdd.state import TicketPipelineState

if TYPE_CHECKING:
    from bp_agents.platform.mcp.contract_broker import ContractBroker
    from bp_agents.platform.tracker import Tracker

logger = logging.getLogger(__name__)

_BP_AGENTS_SEGMENTS = {"bp-agents", ".agents"}


@dataclass
class StageConfig:
    skill: str = ""
    contract_cls: type[BaseModel] = BaseModel
    stage_status: str = ""
    route_result: Callable[[Any, TicketPipelineState], dict] | None = None
    commit: bool = False
    extra_prompt: Callable[[TicketPipelineState], str] | None = None
    max_retries: int = 3


def _run_git(repo_path: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", repo_path, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def build_input_contract(
    ticket_id: str, ticket_body: str, skill: str, context: dict | None = None
) -> dict:
    return {
        "stage": skill.replace("-", "_"),
        "direction": "input",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "skill": skill,
            "ticket": {"id": ticket_id, "body": ticket_body},
            "context": context or {},
        },
    }


def input_contract_to_prompt(contract: dict, outcome_path: str) -> str:
    body = contract["payload"]["ticket"]["body"]
    return (
        f"/{contract['payload']['skill']} {body}\n\n"
        f"outcome_path: {outcome_path}\n\n"
        f"---\n"
        f"When finished, submit the outcome via MCP:\n"
        f"1. Read CONTRACT_BROKER_TOKEN from environment\n"
        f"2. Call the contract-broker submit_contract tool with the token and your outcome payload\n"
        f"The MCP server will validate the payload against the stage schema.\n"
    )


class AgentStageNode:
    def __init__(
        self,
        *,
        sandbox: Sandbox,
        sandbox_config: SandboxConfig,
        target_repo_path: str,
        skills_path: str,
        tracker: "Tracker | None" = None,
        client: OpenCodeClient | None = None,
        otel_port: int | None = None,
        broker: "ContractBroker | None" = None,
        mcp_port: int | None = None,
        stage: StageConfig | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._sandbox_config = sandbox_config
        self._target_repo_path = target_repo_path
        self._skills_path = skills_path
        self._tracker = tracker
        self._client = client
        self._otel_port = otel_port
        self._broker = broker
        self._mcp_port = mcp_port
        cfg = stage or StageConfig()
        self._skill = cfg.skill
        self._contract_cls = cfg.contract_cls
        self._stage_status = cfg.stage_status
        self._route_result = cfg.route_result or (lambda o, s: {"status": "blocked"})
        self._commit = cfg.commit
        self._extra_prompt = cfg.extra_prompt
        self._max_retries = cfg.max_retries

    async def __call__(self, state: TicketPipelineState) -> dict:
        ticket_id = state["ticket_id"]
        project = state.get("project", "unknown")
        ticket_body = state.get("ticket_body", "")

        branch_name: str | None = None
        if self._commit:
            self._check_target_not_bp_agents()
            branch_name = self._ensure_feature_branch(ticket_id)

        input_contract = build_input_contract(ticket_id, ticket_body, self._skill)
        logger.info(
            "ticket %s: dispatching %s  contract=%s",
            ticket_id,
            self._skill,
            json.dumps(input_contract),
        )

        if self._tracker is not None:
            await self._tracker.add_comment(
                ticket_id, json.dumps(input_contract), project
            )
            await self._tracker.update_state(ticket_id, self._stage_status, project)

        agent_config = SKILL_CONFIGS[self._skill]
        outcome_host_path = os.path.join(self._target_repo_path, OUTCOME_FILENAME)
        sandbox_outcome_path = WORKSPACE_MOUNT_PATH + "/" + OUTCOME_FILENAME

        api_key = self._sandbox_config.env.get("OPENROUTER_API_KEY", "")

        extra = self._extra_prompt(state) if self._extra_prompt else ""
        prompt = input_contract_to_prompt(input_contract, sandbox_outcome_path)
        if extra:
            prompt = extra + "\n\n" + prompt

        for attempt in range(1, self._max_retries + 1):
            try:
                outcome = await dispatch(
                    sandbox=self._sandbox,
                    sandbox_config=self._sandbox_config,
                    config=agent_config,
                    skill=self._skill,
                    prompt=prompt,
                    workspace=self._target_repo_path,
                    outcome_path=sandbox_outcome_path,
                    api_key=api_key,
                    ctx=DispatchContext(
                        opencode_client=self._client,
                        otel_port=self._otel_port,
                        broker=self._broker,
                        mcp_port=self._mcp_port,
                    ),
                )
            except (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.HTTPStatusError,
                httpx.TimeoutException,
                TimeoutError,
            ) as exc:
                if attempt < self._max_retries:
                    logger.warning(
                        "ticket %s: sandbox not ready, retrying (%d/%d): %s",
                        ticket_id,
                        attempt,
                        self._max_retries,
                        exc,
                    )
                    await asyncio.sleep(3)
                    continue
                return self._block(state, f"sandbox unreachable: {exc}")
            except FileNotFoundError:
                return self._block(state, "agent: no outcome file written by agent")
            except ContractNotFulfilledError as exc:
                return self._block(state, str(exc))

            try:
                validated = self._contract_cls.model_validate(outcome)
            except ValueError as e:
                logger.error(
                    "ticket %s: invalid %s outcome: %s",
                    ticket_id,
                    self._skill,
                    e,
                )
                return self._block(state, f"agent: invalid outcome: {e}")

            logger.info(
                "ticket %s: %s output  contract=%s",
                ticket_id,
                self._skill,
                json.dumps(validated.model_dump()),
            )

            if self._tracker is not None:
                await self._tracker.add_comment(
                    ticket_id, json.dumps(validated.model_dump()), project
                )

            delta = self._route_result(validated, state)

            if delta.get("blocked_reason"):
                if self._commit:
                    self._clean_artifacts()
                if self._tracker is not None:
                    await self._tracker.update_state(ticket_id, "blocked", project)
                logger.info(
                    "ticket %s: blocked, reason: %s",
                    ticket_id,
                    delta["blocked_reason"],
                )
                return delta

            if self._commit:
                try:
                    self._clean_artifacts()
                    _run_git(self._target_repo_path, "add", "-A")
                    _run_git(
                        self._target_repo_path,
                        "-c",
                        "user.name=bp-agents",
                        "-c",
                        "user.email=bp-agents@localhost",
                        "commit",
                        "-m",
                        f"{self._skill}({ticket_id}): stage complete",
                    )
                except Exception:
                    logger.exception(
                        "ticket %s: git commit failed",
                        ticket_id,
                    )
                    return self._block(state, "auto: git commit failed")

            if self._tracker is not None:
                await self._tracker.update_state(ticket_id, delta["status"], project)

            return delta

        return self._block(state, "auto: max retries exhausted")

    def _block(self, state: TicketPipelineState, reason: str) -> dict:
        logger.info("ticket %s: blocked, reason: %s", state["ticket_id"], reason)
        return {"blocked_reason": reason}

    def _check_target_not_bp_agents(self) -> None:
        parts = os.path.normpath(self._target_repo_path).split(os.sep)
        if _BP_AGENTS_SEGMENTS & set(parts):
            raise RuntimeError(
                f"BP_TARGET_REPO_PATH must not point at bp-agents itself "
                f"(got: {self._target_repo_path})"
            )

    def _ensure_feature_branch(self, ticket_id: str) -> str:
        branch_name = f"feat/{ticket_id.lower()}"
        repo_path = self._target_repo_path

        os.makedirs(repo_path, exist_ok=True)
        try:
            _run_git(
                repo_path, "config", "--global", "--add", "safe.directory", repo_path
            )
        except subprocess.CalledProcessError:
            pass
        try:
            _run_git(repo_path, "rev-parse", "--git-dir")
        except subprocess.CalledProcessError:
            _run_git(repo_path, "init")
            _run_git(repo_path, "checkout", "-b", "main")
            _run_git(
                repo_path,
                "-c",
                "user.name=bp-agents",
                "-c",
                "user.email=bp-agents@localhost",
                "commit",
                "--allow-empty",
                "-m",
                "initial commit",
            )

        try:
            _run_git(self._target_repo_path, "checkout", "-b", branch_name)
        except subprocess.CalledProcessError:
            try:
                _run_git(self._target_repo_path, "checkout", branch_name)
            except subprocess.CalledProcessError:
                try:
                    _run_git(self._target_repo_path, "checkout", "main")
                except subprocess.CalledProcessError:
                    pass
                try:
                    _run_git(self._target_repo_path, "checkout", "-b", branch_name)
                except subprocess.CalledProcessError:
                    raise RuntimeError(
                        f"Failed to create or checkout feature branch "
                        f"'{branch_name}' in {self._target_repo_path}"
                    )
        return branch_name

    def _clean_artifacts(self) -> None:
        outcome = os.path.join(self._target_repo_path, OUTCOME_FILENAME)
        if os.path.exists(outcome):
            os.remove(outcome)
        opencode_json = os.path.join(self._target_repo_path, "opencode.json")
        if os.path.exists(opencode_json):
            os.remove(opencode_json)
