import dataclasses
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from bp_agents.platform.agent_client import OpenCodeClient
from bp_agents.platform.sandbox import Sandbox, SandboxConfig
from bp_agents.workflows.sdd.contracts import TddOutput
from bp_agents.workflows.sdd.state import TicketPipelineState

if TYPE_CHECKING:
    from bp_agents.platform.tracker import Tracker

logger = logging.getLogger(__name__)

_TDD_SKILL = "tdd"


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
    if data["status"] not in ("DONE", "DONE_WITH_CONCERNS", "BLOCKED"):
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
    ) -> None:
        self._sandbox = sandbox
        self._sandbox_config = sandbox_config
        self._target_repo_path = target_repo_path
        self._skills_path = skills_path
        self._tracker = tracker

    async def __call__(self, state: TicketPipelineState) -> dict:
        ticket_id = state["ticket_id"]
        project = state.get("project", "unknown")
        ticket_body = state.get("ticket_body", "")

        self._prepare_workspace()
        branch_name = self._ensure_feature_branch(ticket_id)

        input_contract = build_input_contract(ticket_id, ticket_body)
        logger.info(
            "ticket %s: dispatching tdd  contract=%s",
            ticket_id,
            json.dumps(input_contract),
        )

        outcome_host_path = os.path.join(self._target_repo_path, "outcome.json")
        config = dataclasses.replace(
            self._sandbox_config,
            workspace_path=self._target_repo_path,
            workspace_mode="rw",
            env={
                **self._sandbox_config.env,
                "outcome_path": "/data/workspace/outcome.json",
            },
        )

        session = await self._sandbox.create(config)
        try:
            client = OpenCodeClient(session.base_url)
            try:
                oc_session = await client.create_session(agent="builder")
                await client.prompt(oc_session, json.dumps(input_contract))
                await client.wait(oc_session)
            finally:
                await client.close()

            try:
                tdd_output = self._read_and_validate_outcome(
                    ticket_id, outcome_host_path
                )
            except OutcomeMissingError:
                return {
                    "status": "blocked",
                    "blocked_reason": "agent: no outcome file written by agent",
                }

            logger.info(
                "ticket %s: tdd output  contract=%s",
                ticket_id,
                json.dumps(tdd_output),
            )

            if tdd_output["status"] == "BLOCKED":
                return await self._handle_blocked(state, tdd_output)

            return await self._handle_complete(state, tdd_output, branch_name)
        finally:
            await self._sandbox.destroy(session.container_id)

    def _prepare_workspace(self) -> None:
        skills_dest = os.path.join(self._target_repo_path, ".agents", "skills")
        os.makedirs(skills_dest, exist_ok=True)
        if os.path.isdir(self._skills_path):
            shutil.rmtree(skills_dest, ignore_errors=True)
            shutil.copytree(self._skills_path, skills_dest)

    def _ensure_feature_branch(self, ticket_id: str) -> str:
        branch_name = f"feat/{ticket_id.lower()}"
        try:
            _run_git(self._target_repo_path, "checkout", "-b", branch_name)
        except subprocess.CalledProcessError:
            try:
                _run_git(self._target_repo_path, "checkout", branch_name)
            except subprocess.CalledProcessError:
                self._run_git_if_possible("checkout", "main")
                try:
                    _run_git(self._target_repo_path, "checkout", "-b", branch_name)
                except subprocess.CalledProcessError:
                    pass
        return branch_name

    def _run_git_if_possible(self, *args: str) -> None:
        try:
            _run_git(self._target_repo_path, *args)
        except subprocess.CalledProcessError:
            pass

    def _read_and_validate_outcome(
        self, ticket_id: str, outcome_host_path: str
    ) -> TddOutput:
        try:
            with open(outcome_host_path) as f:
                output_data = json.load(f)
        except FileNotFoundError:
            logger.error(
                "ticket %s: no outcome file found at %s",
                ticket_id,
                outcome_host_path,
            )
            raise OutcomeMissingError(ticket_id)
        return validate_tdd_output(output_data)

    async def _handle_blocked(
        self, state: TicketPipelineState, tdd_output: TddOutput
    ) -> dict:
        ticket_id = state["ticket_id"]
        concerns = tdd_output.get("concerns") or []
        detail = "; ".join(concerns).strip()
        reason = f"agent: {detail}" if detail else "agent: blocked"
        logger.info("ticket %s: blocked, reason: %s", ticket_id, reason)
        if self._tracker is not None:
            await self._tracker.update_state(
                ticket_id, "blocked", state.get("project", "unknown")
            )
        return {
            "status": "blocked",
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
        outcome = os.path.join(self._target_repo_path, "outcome.json")
        if os.path.exists(outcome):
            os.remove(outcome)
        skills = os.path.join(self._target_repo_path, ".agents")
        if os.path.isdir(skills):
            shutil.rmtree(skills, ignore_errors=True)


class OutcomeMissingError(Exception):
    def __init__(self, ticket_id: str) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"ticket {ticket_id}: no outcome file written by agent")
