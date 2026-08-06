import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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

    def test_valid_fail(self) -> None:
        data = {
            "status": "FAIL",
            "summary": "Transient error",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Network timeout"],
        }
        result = validate_tdd_output(data)
        assert result["status"] == "FAIL"

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
    """TddNode tests with mocked sandbox, dispatch, and git."""

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

    def _write_agent_code(self, repo_path: Path) -> None:
        (repo_path / "hello.py").write_text("def hello():\n    return 'hello world'\n")

    @pytest.fixture
    def tracker(self) -> MagicMock:
        t = MagicMock()
        t.update_state = AsyncMock()
        t.add_comment = AsyncMock()
        return t

    async def test_tdd_complete_creates_branch_and_commits(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "DONE",
            "summary": "Implemented hello world",
            "test_results": {"passed": 3, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        self._write_agent_code(target_repo)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(return_value=outcome),
        ):
            result = await node(_make_state())

        assert result["status"] == "awaiting_review"
        assert result["tdd_output"]["status"] == "DONE"
        assert result["tdd_output"]["summary"] == "Implemented hello world"

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

        tracker.update_state.assert_any_call("TICK-1", "implementing", "project-1")
        tracker.update_state.assert_any_call("TICK-1", "awaiting_review", "project-1")
        tracker.add_comment.assert_called()

    async def test_tdd_blocked_does_not_commit(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "BLOCKED",
            "summary": "Missing dependency",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(return_value=outcome),
        ):
            result = await node(_make_state())

        assert result["blocked_reason"] == (
            "agent: Module utils.validators not yet implemented"
        )
        assert "status" not in result
        assert result["tdd_output"]["status"] == "BLOCKED"

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" not in log.stdout
        assert "initial" in log.stdout

        tracker.update_state.assert_any_call("TICK-1", "implementing", "project-1")
        tracker.update_state.assert_any_call("TICK-1", "blocked", "project-1")
        tracker.add_comment.assert_called()

    async def test_tdd_missing_outcome_returns_blocked(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
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
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(side_effect=FileNotFoundError("outcome.json not found")),
        ):
            result = await node(_make_state())

        assert "status" not in result
        assert "no outcome file" in result.get("blocked_reason", "").lower()

    async def test_tdd_cleans_artifacts_before_commit(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "DONE",
            "summary": "Done",
            "test_results": {"passed": 1, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        self._write_agent_code(target_repo)

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(return_value=outcome),
        ):
            await node(_make_state())

        assert not (target_repo / "outcome.json").exists()
        assert not (target_repo / "opencode.json").exists()
        assert (target_repo / "hello.py").exists()

    async def test_tdd_blocked_cleans_artifacts(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "BLOCKED",
            "summary": "Missing dep",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module missing"],
        }

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(return_value=outcome),
        ):
            await node(_make_state())

        assert not (target_repo / "outcome.json").exists()

    async def test_tdd_fail_status_handled_as_blocked(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        outcome = {
            "status": "FAIL",
            "summary": "Transient error",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Network timeout"],
        }

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(return_value=outcome),
        ):
            result = await node(_make_state())

        assert "status" not in result
        assert "transient" in result["blocked_reason"]

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" not in log.stdout

    async def test_nfr_guard_rejects_bp_agents_target(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        bp_agents_path = str(Path(tempfile.mkdtemp()) / "bp-agents" / "subdir")
        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=bp_agents_path,
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with pytest.raises(RuntimeError, match="bp-agents"):
            await node(_make_state())

    async def test_nfr_guard_rejects_dot_agents_segment(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        dangerous_path = str(Path(tempfile.mkdtemp()) / "some-project" / ".agents")
        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=dangerous_path,
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        with pytest.raises(RuntimeError, match="bp-agents"):
            await node(_make_state())

    async def test_ensure_feature_branch_auto_inits_non_repo(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
    ) -> None:
        non_repo = Path(tempfile.mkdtemp())
        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(non_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        branch = node._ensure_feature_branch("TICK-99")
        assert branch == "feat/tick-99"

        branch_out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=non_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert branch_out.stdout.strip() == "feat/tick-99"

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=non_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "initial commit" in log.stdout

    async def test_connect_error_logs_correct_format_and_updates_tracker(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
        )

        caplog.set_level(logging.INFO)

        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(
                side_effect=httpx.ConnectError(
                    "All connection attempts failed",
                    request=MagicMock(),
                )
            ),
        ):
            result = await node(_make_state())

        assert "status" not in result
        assert "sandbox unreachable" in result["blocked_reason"]

        messages = [r.message for r in caplog.records]
        assert any(
            "blocked, reason: sandbox unreachable" in m for m in messages
        ), "ConnectError must log 'blocked, reason: sandbox unreachable' (AC-11)"

    async def test_read_timeout_retries_then_blocked(
        self,
        target_repo: Path,
        skills_dir: Path,
        mock_sandbox: MagicMock,
        sandbox_config: SandboxConfig,
        tracker: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        node = TddNode(
            sandbox=mock_sandbox,
            sandbox_config=sandbox_config,
            target_repo_path=str(target_repo),
            skills_path=str(skills_dir),
            tracker=tracker,
            max_retries=2,
        )

        caplog.set_level(logging.WARNING)

        mock_req = MagicMock()
        with patch(
            "bp_agents.workflows.sdd.tdd.dispatch",
            AsyncMock(
                side_effect=httpx.ReadTimeout(
                    "POST /session/sess-1/message timed out",
                    request=mock_req,
                )
            ),
        ):
            result = await node(_make_state())

        assert "status" not in result
        assert "sandbox unreachable" in result["blocked_reason"]

        retry_messages = [r.message for r in caplog.records if "retrying" in r.message]
        assert (
            len(retry_messages) == 1
        ), f"Expected 1 retry log message, got {len(retry_messages)}"
