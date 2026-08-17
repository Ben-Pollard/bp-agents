import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bp_agents.platform.mcp.contract_broker import ContractNotFulfilledError
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.workflows.sdd.contracts import TddOutput
from bp_agents.workflows.sdd.nodes.agent_stage import (
    AgentStageNode,
    build_input_contract,
)
from bp_agents.workflows.sdd.state import TicketPipelineState


def _make_state(**overrides: str) -> TicketPipelineState:
    base: TicketPipelineState = {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "ticket_body": "Write a function that returns hello world and a test.",
        "status": "ready",
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "qa_output": None,
        "diff": None,
        "review_approved": None,
        "verification_passed": None,
        "blocked_reason": None,
    }
    base.update(**overrides)
    return base


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
    def target_repo(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=tmp, capture_output=True, check=True
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@test",
                "commit",
                "--allow-empty",
                "-m",
                "initial",
            ],
            cwd=tmp,
            capture_output=True,
            check=True,
        )
        return tmp

    @pytest.fixture
    def mock_sandbox(self) -> MagicMock:
        sandbox = MagicMock()
        sandbox.create = AsyncMock(
            return_value=SandboxSession(
                container_id="c1", port=32768, base_url="http://localhost:32768"
            )
        )
        sandbox.destroy = AsyncMock()
        return sandbox

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
            skill="tdd",
            contract_cls=TddOutput,
            stage_status="implementing",
            commit=True,
            route_result=lambda o, s: (
                {"status": "awaiting_review", "tdd_output": o}
                if o.status == "DONE"
                else {"blocked_reason": f"agent: {o.status}"}
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
            result = await node(_make_state())

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
            result = await node(_make_state())

        assert result.get("blocked_reason") is not None
        assert "BLOCKED" in result["blocked_reason"]

    async def test_dispatch_connection_error_retries_then_blocks(
        self, node: AgentStageNode
    ) -> None:
        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        dispatch_mock = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch.object(stage_module, "dispatch", dispatch_mock):
            result = await node(_make_state())

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
            result = await node(_make_state())

        assert result.get("blocked_reason") is not None

    async def test_invalid_outcome_blocks(self, node: AgentStageNode) -> None:
        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        dispatch_mock = AsyncMock(return_value={"bad": "data"})

        with patch.object(stage_module, "dispatch", dispatch_mock):
            result = await node(_make_state())

        assert result.get("blocked_reason") is not None
        assert "invalid" in result["blocked_reason"].lower()
