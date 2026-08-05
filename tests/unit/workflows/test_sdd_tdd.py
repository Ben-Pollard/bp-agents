import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.workflows.sdd.state import TicketPipelineState
from bp_agents.workflows.sdd.tdd import (
    TddNode,
    build_input_contract,
    validate_tdd_output,
)


def _make_state(**overrides: str) -> TicketPipelineState:
    base: TicketPipelineState = {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "ticket_body": "Write a function that returns hello world and a test.",
        "status": "ready",
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
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
        result = validate_tdd_output(data)
        assert result["status"] == "DONE"

    def test_valid_done_with_concerns(self) -> None:
        data = {
            "status": "DONE_WITH_CONCERNS",
            "summary": "Works but slow",
            "test_results": {"passed": 5, "failed": 0, "skipped": 0},
            "concerns": ["Performance needs improvement"],
        }
        result = validate_tdd_output(data)
        assert result["status"] == "DONE_WITH_CONCERNS"

    def test_valid_blocked(self) -> None:
        data = {
            "status": "BLOCKED",
            "summary": "Cannot proceed",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }
        result = validate_tdd_output(data)
        assert result["status"] == "BLOCKED"

    def test_missing_field_raises(self) -> None:
        with pytest.raises(ValueError, match="missing fields"):
            validate_tdd_output({"status": "DONE"})

    def test_invalid_status_raises(self) -> None:
        data = {
            "status": "INVALID",
            "summary": "",
            "test_results": {},
            "concerns": [],
        }
        with pytest.raises(ValueError, match="Invalid TddOutput status"):
            validate_tdd_output(data)


class TestBuildInputContract:
    def test_contains_stage_and_direction(self) -> None:
        contract = build_input_contract("TICK-1", "body")
        assert contract["stage"] == "tdd"
        assert contract["direction"] == "input"
        assert "timestamp" in contract

    def test_contains_skill_in_payload(self) -> None:
        contract = build_input_contract("TICK-1", "body")
        assert contract["payload"]["skill"] == "tdd"

    def test_contains_ticket_body(self) -> None:
        contract = build_input_contract("TICK-1", "Write a function")
        assert contract["payload"]["ticket"]["id"] == "TICK-1"
        assert contract["payload"]["ticket"]["body"] == "Write a function"

    def test_contains_carry_forward_context(self) -> None:
        contract = build_input_contract(
            "TICK-1", "body", context={"prior_summary": "done"}
        )
        assert contract["payload"]["context"] == {"prior_summary": "done"}

    def test_context_defaults_to_empty(self) -> None:
        contract = build_input_contract("TICK-1", "body")
        assert contract["payload"]["context"] == {}


class TestTddNode:
    """TddNode tests with mocked sandbox, client, and git."""

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
    def skills_dir(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "tdd.md").write_text("# TDD skill")
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
    def sandbox_config(self) -> SandboxConfig:
        return SandboxConfig(
            image="symphony-agent:latest",
            workspace_path="/tmp/ws",
            skills_path="/tmp/skills",
            runtime="",
            timeout_seconds=60,
        )

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        client.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
        client.prompt = AsyncMock()
        client.wait = AsyncMock()
        client.close = AsyncMock()
        return client

    def _write_outcome(self, repo_path: Path, data: dict) -> None:
        (repo_path / "outcome.json").write_text(json.dumps(data))

    def _write_agent_code(self, repo_path: Path) -> None:
        (repo_path / "hello.py").write_text("def hello():\n    return 'hello world'\n")

    @pytest.fixture
    def tracker(self) -> MagicMock:
        t = MagicMock()
        t.update_state = AsyncMock()
        return t

    async def test_tdd_complete_creates_branch_and_commits(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        mock_client: MagicMock,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "DONE",
            "summary": "Implemented hello world",
            "test_results": {"passed": 3, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        self._write_outcome(target_repo, outcome)
        self._write_agent_code(target_repo)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.OpenCodeClient", return_value=mock_client
        ):
            result = await node(_make_state())

        assert result["status"] == "awaiting_review"
        assert result["tdd_output"]["status"] == "DONE"
        assert result["tdd_output"]["summary"] == "Implemented hello world"

        mock_sandbox.create.assert_called_once()
        mock_sandbox.destroy.assert_called_once()

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" in log.stdout

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert branch.stdout.strip() == "feat/tick-1"

        tracker.update_state.assert_called_once_with(
            "TICK-1", "awaiting_review", "project-1"
        )

    async def test_tdd_blocked_does_not_commit(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        mock_client: MagicMock,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "BLOCKED",
            "summary": "Missing dependency",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }
        self._write_outcome(target_repo, outcome)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.OpenCodeClient", return_value=mock_client
        ):
            result = await node(_make_state())

        assert result["status"] == "blocked"
        assert result["blocked_reason"] == (
            "agent: Module utils.validators not yet implemented"
        )
        assert result["tdd_output"]["status"] == "BLOCKED"

        mock_sandbox.create.assert_called_once()
        mock_sandbox.destroy.assert_called_once()

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" not in log.stdout
        assert "initial" in log.stdout

        tracker.update_state.assert_called_once_with("TICK-1", "blocked", "project-1")

    async def test_tdd_missing_outcome_returns_blocked(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        mock_client: MagicMock,
        tracker: MagicMock,
    ) -> None:
        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.OpenCodeClient", return_value=mock_client
        ):
            result = await node(_make_state())

        assert result["status"] == "blocked"
        assert "no outcome file" in result.get("blocked_reason", "").lower()

        mock_sandbox.create.assert_called_once()
        mock_sandbox.destroy.assert_called_once()

    async def test_tdd_cleans_artifacts_before_commit(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        mock_client: MagicMock,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "DONE",
            "summary": "Done",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        self._write_outcome(target_repo, outcome)
        self._write_agent_code(target_repo)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.OpenCodeClient", return_value=mock_client
        ):
            await node(_make_state())

        assert not (target_repo / "outcome.json").exists()
        assert not (target_repo / ".agents").exists()
        assert (target_repo / "hello.py").exists()

    async def test_tdd_complete_uses_sandbox_config_with_writable_workspace(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        mock_client: MagicMock,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "DONE",
            "summary": "Done",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        self._write_outcome(target_repo, outcome)
        self._write_agent_code(target_repo)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.OpenCodeClient", return_value=mock_client
        ):
            await node(_make_state())

        call_kwargs = mock_sandbox.create.call_args[0][0]
        assert call_kwargs.workspace_mode == "rw"
        assert call_kwargs.workspace_path == str(target_repo)
        assert "outcome_path" in call_kwargs.env
        assert call_kwargs.env["outcome_path"] == "/data/workspace/outcome.json"
