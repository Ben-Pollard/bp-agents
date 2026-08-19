import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from bp_agents.platform.mcp.contract_broker import ContractNotFulfilledError
from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.workflows.sdd.contracts import TddOutput
from bp_agents.workflows.sdd.nodes.agent_stage import (
    AgentStageNode,
    StageConfig,
    build_input_contract,
)
from tests.conftest import ts_ready


class TestValidateTddOutput:
    def test_valid_complete(self) -> None:
        data = {
            "status": "DONE",
            "summary": "All tests pass",
            "test_results": {"passed": 5, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        result = TddOutput.model_validate(data)
        assert result.status == "DONE"

    def test_valid_done_with_concerns(self) -> None:
        data = {
            "status": "DONE_WITH_CONCERNS",
            "summary": "Works but slow",
            "test_results": {"passed": 5, "failed": 0, "skipped": 0},
            "concerns": ["Performance needs improvement"],
        }
        result = TddOutput.model_validate(data)
        assert result.status == "DONE_WITH_CONCERNS"

    def test_valid_blocked(self) -> None:
        data = {
            "status": "BLOCKED",
            "summary": "Cannot proceed",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }
        result = TddOutput.model_validate(data)
        assert result.status == "BLOCKED"

    def test_valid_fail(self) -> None:
        data = {
            "status": "FAIL",
            "summary": "Transient error",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Network timeout"],
        }
        result = TddOutput.model_validate(data)
        assert result.status == "FAIL"

    def test_missing_field_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="Field required"):
            TddOutput.model_validate({"status": "DONE"})

    def test_invalid_status_raises(self) -> None:
        from pydantic import ValidationError

        data = {
            "status": "INVALID",
            "summary": "",
            "test_results": {},
            "concerns": [],
        }
        with pytest.raises(ValidationError, match="Input should be"):
            TddOutput.model_validate(data)


class TestBuildInputContract:
    def test_contains_stage_and_direction(self) -> None:
        contract = build_input_contract("TICK-1", "body", "tdd")
        assert contract["stage"] == "tdd"
        assert contract["direction"] == "input"
        assert "timestamp" in contract

    def test_contains_skill_in_payload(self) -> None:
        contract = build_input_contract("TICK-1", "body", "tdd")
        assert contract["payload"]["skill"] == "tdd"

    def test_contains_ticket_body(self) -> None:
        contract = build_input_contract("TICK-1", "Write a function", "tdd")
        assert contract["payload"]["ticket"]["id"] == "TICK-1"
        assert contract["payload"]["ticket"]["body"] == "Write a function"

    def test_contains_carry_forward_context(self) -> None:
        contract = build_input_contract(
            "TICK-1", "body", "tdd", context={"prior_summary": "done"}
        )
        assert contract["payload"]["context"] == {"prior_summary": "done"}

    def test_context_defaults_to_empty(self) -> None:
        contract = build_input_contract("TICK-1", "body", "tdd")
        assert contract["payload"]["context"] == {}


class TestAgentStageNode:
    """AgentStageNode tests with mocked sandbox, dispatch, and git."""

    @pytest.fixture
    def node(self, target_repo, mock_sandbox) -> AgentStageNode:
        return AgentStageNode(
            sandbox=mock_sandbox,
            sandbox_config=SandboxConfig(
                image="opencode-agent:latest",
                workspace_path=str(target_repo),
                skills_path=str(target_repo / "skills"),
                runtime="",
                env={"OPENROUTER_API_KEY": "sk-test"},
            ),
            target_repo_path=str(target_repo),
            skills_path=str(target_repo / "skills"),
            tracker=None,
            client=None,
            stage=StageConfig(
                skill="tdd",
                contract_cls=TddOutput,
                stage_status="implementing",
                commit=True,
                route_result=lambda o, s: (
                    {"status": "awaiting_review", "tdd_output": o}
                    if o.status == "DONE"
                    else {"blocked_reason": f"agent: {o.status}"}
                ),
            ),
        )

    async def test_success_routes_to_awaiting_review(
        self, node: AgentStageNode, target_repo: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        (target_repo / "hello.py").write_text(
            "def hello():\n    return 'hello world'\n"
        )

        outcome = {
            "status": "DONE",
            "summary": "All tests pass",
            "test_results": {"passed": 5, "failed": 0, "skipped": 0},
            "concerns": [],
        }

        caplog.set_level(logging.INFO)

        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        with patch.object(stage_module, "dispatch", AsyncMock(return_value=outcome)):
            result = await node(ts_ready("ready"))

        assert result["status"] == "awaiting_review"
        assert result["tdd_output"].status == "DONE"

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "tdd(TICK-1)" in log.stdout

    async def test_blocked_outcome_routes_to_blocked(
        self, node: AgentStageNode, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        outcome = {
            "status": "BLOCKED",
            "summary": "Missing dependency",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }

        caplog.set_level(logging.INFO)

        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        with patch.object(stage_module, "dispatch", AsyncMock(return_value=outcome)):
            result = await node(ts_ready("ready"))

        assert result.get("blocked_reason") is not None
        assert "BLOCKED" in result["blocked_reason"]

    async def test_dispatch_connection_error_retries_then_blocks(
        self, node: AgentStageNode
    ) -> None:
        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        dispatch_mock = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch.object(stage_module, "dispatch", dispatch_mock):
            result = await node(ts_ready("ready"))

        assert result.get("blocked_reason") is not None
        assert "connection refused" in result["blocked_reason"].lower()

    async def test_dispatch_contract_not_fulfilled_blocks(
        self, node: AgentStageNode
    ) -> None:
        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        dispatch_mock = AsyncMock(
            side_effect=ContractNotFulfilledError("no contract submitted")
        )

        with patch.object(stage_module, "dispatch", dispatch_mock):
            result = await node(ts_ready("ready"))

        assert result.get("blocked_reason") is not None

    async def test_invalid_outcome_blocks(self, node: AgentStageNode) -> None:
        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        dispatch_mock = AsyncMock(return_value={"bad": "data"})

        with patch.object(stage_module, "dispatch", dispatch_mock):
            result = await node(ts_ready("ready"))

        assert result.get("blocked_reason") is not None
        assert "invalid" in result["blocked_reason"].lower()
