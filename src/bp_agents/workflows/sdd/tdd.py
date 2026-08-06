import asyncio
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.dispatch import OUTCOME_FILENAME, dispatch
from bp_agents.platform.sandbox import Sandbox, SandboxConfig
from bp_agents.workflows.sdd.contracts import TddOutput
from bp_agents.workflows.sdd.skill_configs import SKILL_CONFIGS
from bp_agents.workflows.sdd.state import TicketPipelineState

if TYPE_CHECKING:
    from bp_agents.platform.tracker import Tracker

logger = logging.getLogger(__name__)

_TDD_SKILL = "tdd"

_BP_AGENTS_SEGMENTS = {"bp-agents", ".agents"}


def _run_git(repo_path: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", repo_path, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def validate_tdd_output(data: dict) -> TddOutput:
    required = {"status", "summary", "test_results", "concerns"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Invalid TddOutput, missing fields: {sorted(missing)}")
    if data["status"] not in ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "FAIL"):
        raise ValueError(f"Invalid TddOutput status: {data['status']}")
    return TddOutput(**data)


def build_input_contract(
    ticket_id: str, ticket_body: str, context: dict | None = None
) -> dict:
    return {
        "stage": "tdd",
        "direction": "input",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "skill": _TDD_SKILL,
            "ticket": {"id": ticket_id, "body": ticket_body},
            "context": context or {},
        },
    }


class TddNode:
    def __init__(
        self,
        sandbox: Sandbox,
        sandbox_config: SandboxConfig,
        target_repo_path: str,
        skills_path: str,
        tracker: "Tracker | None" = None,
        client: OpenCodeClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._sandbox = sandbox
        self._sandbox_config = sandbox_config
        self._target_repo_path = target_repo_path
        self._skills_path = skills_path
        self._tracker = tracker
        self._client = client
        self._max_retries = max_retries

    async def __call__(self, state: TicketPipelineState) -> dict:
        ticket_id = state["ticket_id"]
        project = state.get("project", "unknown")
        ticket_body = state.get("ticket_body", "")

        self._check_target_not_bp_agents()
        branch_name = self._ensure_feature_branch(ticket_id)

        input_contract = build_input_contract(ticket_id, ticket_body)
        logger.info(
            "ticket %s: dispatching tdd  contract=%s",
            ticket_id,
            json.dumps(input_contract),
        )

        if self._tracker is not None:
            await self._tracker.add_comment(
                ticket_id, json.dumps(input_contract), project
            )
            await self._tracker.update_state(ticket_id, "implementing", project)

        agent_config = SKILL_CONFIGS[_TDD_SKILL]
        outcome_host_path = os.path.join(self._target_repo_path, OUTCOME_FILENAME)
        sandbox_outcome_path = "/data/workspace/" + OUTCOME_FILENAME

        api_key = self._sandbox_config.env.get("OPENROUTER_API_KEY", "")

        for attempt in range(1, self._max_retries + 1):
            try:
                outcome = await dispatch(
                    sandbox=self._sandbox,
                    sandbox_config=self._sandbox_config,
                    config=agent_config,
                    skill=_TDD_SKILL,
                    prompt=json.dumps(input_contract),
                    workspace=self._target_repo_path,
                    outcome_path=sandbox_outcome_path,
                    api_key=api_key,
                    opencode_client=self._client,
                )
            except (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.HTTPStatusError,
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
                logger.error(
                    "ticket %s: blocked, reason: sandbox unreachable: %s",
                    ticket_id,
                    exc,
                )
                return {
                    "blocked_reason": f"sandbox unreachable: {exc}",
                }
            except FileNotFoundError:
                return {
                    "blocked_reason": "agent: no outcome file written by agent",
                }

            try:
                tdd_output = validate_tdd_output(outcome)
            except ValueError as e:
                logger.error("ticket %s: invalid outcome: %s", ticket_id, e)
                return {
                    "blocked_reason": f"agent: invalid outcome: {e}",
                }

            logger.info(
                "ticket %s: tdd output  contract=%s",
                ticket_id,
                json.dumps(tdd_output),
            )

            if self._tracker is not None:
                await self._tracker.add_comment(
                    ticket_id, json.dumps(tdd_output), project
                )

            if tdd_output["status"] == "FAIL":
                if attempt < self._max_retries:
                    logger.info(
                        "ticket %s: transient fail, retrying (%d/%d)",
                        ticket_id,
                        attempt,
                        self._max_retries,
                    )
                    continue
                logger.info(
                    "ticket %s: transient fail, exhausted %d retries",
                    ticket_id,
                    self._max_retries,
                )
                return await self._handle_non_complete(
                    state,
                    tdd_output,
                    "fail",
                    "auto: transient failure: ",
                    "auto: transient failure",
                )

            if tdd_output["status"] == "BLOCKED":
                return await self._handle_non_complete(
                    state,
                    tdd_output,
                    "blocked",
                    "agent: ",
                    "agent: blocked",
                )

            return await self._handle_complete(state, tdd_output, branch_name)

        return {"blocked_reason": "auto: max retries exhausted"}

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
                        f"Failed to create or checkout feature branch '{branch_name}' "
                        f"in {self._target_repo_path}"
                    )
        return branch_name

    async def _handle_non_complete(
        self,
        state: TicketPipelineState,
        tdd_output: TddOutput,
        log_kind: str,
        reason_prefix: str,
        default_reason: str,
    ) -> dict:
        ticket_id = state["ticket_id"]
        concerns = tdd_output.get("concerns") or []
        detail = "; ".join(concerns).strip()
        reason = f"{reason_prefix}{detail}" if detail else default_reason
        logger.info("ticket %s: %s, reason: %s", ticket_id, log_kind, reason)
        self._clean_artifacts()
        if self._tracker is not None:
            await self._tracker.update_state(
                ticket_id, "blocked", state.get("project", "unknown")
            )
        return {
            "blocked_reason": reason,
            "tdd_output": tdd_output,
        }

    async def _handle_complete(
        self,
        state: TicketPipelineState,
        tdd_output: TddOutput,
        branch_name: str,
    ) -> dict:
        ticket_id = state["ticket_id"]
        self._clean_artifacts()
        _run_git(self._target_repo_path, "add", "-A")
        _run_git(
            self._target_repo_path,
            "commit",
            "-m",
            f"feat({ticket_id}): TDD implementation",
        )
        logger.info("ticket %s: implementing -> awaiting-review", ticket_id)
        if self._tracker is not None:
            await self._tracker.update_state(
                ticket_id, "awaiting_review", state.get("project", "unknown")
            )
        return {"status": "awaiting_review", "tdd_output": tdd_output}

    def _clean_artifacts(self) -> None:
        outcome = os.path.join(self._target_repo_path, OUTCOME_FILENAME)
        if os.path.exists(outcome):
            os.remove(outcome)
        opencode_json = os.path.join(self._target_repo_path, "opencode.json")
        if os.path.exists(opencode_json):
            os.remove(opencode_json)


class OutcomeMissingError(Exception):
    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"ticket {ticket_id}: no outcome file written by agent")
