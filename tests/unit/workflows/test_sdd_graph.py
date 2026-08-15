import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.workflows.sdd.graph import (
    build_ticket_pipeline,
    route_review,
    route_ticket,
    route_verify,
)
from bp_agents.workflows.sdd.state import TicketPipelineState


def test_build_ticket_pipeline_compiles() -> None:
    app = build_ticket_pipeline()
    assert app is not None


def _ts(
    status: str,
    review_approved: bool | None = None,
    verification_passed: bool | None = None,
    blocked_reason: str | None = None,
    ticket_body: str = "",
) -> TicketPipelineState:
    return {
        "ticket_id": "TICK-1",
        "project": "project-1",
        "ticket_body": ticket_body,
        "status": status,
        "tdd_output": None,
        "review_output": None,
        "revision_output": None,
        "diff": None,
        "review_approved": review_approved,
        "verification_passed": verification_passed,
        "blocked_reason": blocked_reason,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ready", "implement"),
        ("implementing", END),
        ("awaiting_review", "review"),
        ("awaiting_revision", "revise"),
        ("revising", "revise_complete"),
        ("awaiting_verification", "verify"),
        ("awaiting_approval", "approve_final"),
        ("done", END),
        ("blocked", END),
    ],
)
def test_route_ticket_returns_next_node(status: str, expected: str) -> None:
    assert route_ticket(_ts(status)) == expected


def test_route_review_returns_approve_by_default() -> None:
    assert route_review(_ts("reviewing")) == "approve_review"


def test_route_review_returns_request_changes_when_not_approved() -> None:
    assert route_review(_ts("reviewing", review_approved=False)) == "request_changes"


def test_route_verify_returns_pass_by_default() -> None:
    assert route_verify(_ts("verifying")) == "verification_pass"


def test_route_verify_returns_fail_when_not_passed() -> None:
    assert (
        route_verify(_ts("verifying", verification_passed=False)) == "verification_fail"
    )


def test_route_ticket_returns_block_when_blocked_reason() -> None:
    assert route_ticket(_ts("ready", blocked_reason="blocking issue")) == "block"


def test_route_ticket_returns_block_when_blocked_reason_and_implementing() -> None:
    assert route_ticket(_ts("implementing", blocked_reason="dep on API")) == "block"


def test_route_ticket_ignores_blocked_reason_when_already_blocked() -> None:
    assert route_ticket(_ts("blocked", blocked_reason="still blocked")) == END


def test_pipeline_advances_ready_to_blocked_without_sandbox() -> None:
    app = build_ticket_pipeline()
    initial = _ts("ready")
    result = app.invoke(initial, {"configurable": {"thread_id": "TICK-1"}})
    assert result["status"] == "blocked"
    assert result["blocked_reason"] is not None
    assert "BP_TARGET_REPO_PATH" in result["blocked_reason"]


def test_pipeline_flow_from_awaiting_revision() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-3"}}
    initial = _ts("awaiting_revision")
    result = app.invoke(initial, config)
    assert result["status"] == "done"


def test_pipeline_flow_from_awaiting_verification() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-4"}}
    initial = _ts("awaiting_verification")
    result = app.invoke(initial, config)
    assert result["status"] == "done"


class TestTddGraphWire:
    """Tracer bullet: ticket flows through the graph with a mocked TddNode dispatch."""

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

    async def test_ready_ticket_with_tdd_success_reaches_awaiting_review(
        self,
        target_repo: Path,
        mock_sandbox: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        (target_repo / "hello.py").write_text(
            "def hello():\n    return 'hello world'\n"
        )
        outcome = {
            "status": "DONE",
            "summary": "Implemented hello world",
            "test_results": {"passed": 3, "failed": 0, "skipped": 0},
            "concerns": [],
        }

        app = build_ticket_pipeline(
            sandbox=mock_sandbox,
            sandbox_config=SandboxConfig(
                image="opencode-agent:latest",
                workspace_path=str(target_repo),
                skills_path=str(target_repo / "skills"),
                runtime="",
            ),
            target_repo_path=str(target_repo),
            skills_path=str(target_repo / "skills"),
        )

        caplog.set_level(logging.INFO)

        import bp_agents.workflows.sdd.nodes.tdd as tdd_module

        with patch.object(tdd_module, "dispatch", AsyncMock(return_value=outcome)):
            result = await app.ainvoke(
                _ts("ready", ticket_body="Write a hello world function"),
                {"configurable": {"thread_id": "TICK-1"}},
            )

        assert result["tdd_output"].status == "DONE"

        messages = [r.message for r in caplog.records]
        assert any("dispatching tdd" in m for m in messages)
        assert any(
            "implementing -> awaiting-review" in m or "implementing -> awaiting" in m
            for m in messages
        )
        assert any("tdd output" in m for m in messages)

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" in log.stdout

    async def test_ready_ticket_with_tdd_blocked_reaches_blocked(
        self,
        target_repo: Path,
        mock_sandbox: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        outcome = {
            "status": "BLOCKED",
            "summary": "Missing dependency",
            "test_results": {"passed": 0, "failed": 0, "skipped": 0},
            "concerns": ["Module utils.validators not yet implemented"],
        }

        app = build_ticket_pipeline(
            sandbox=mock_sandbox,
            sandbox_config=SandboxConfig(
                image="opencode-agent:latest",
                workspace_path=str(target_repo),
                skills_path=str(target_repo / "skills"),
                runtime="",
            ),
            target_repo_path=str(target_repo),
            skills_path=str(target_repo / "skills"),
        )

        caplog.set_level(logging.INFO)

        import bp_agents.workflows.sdd.nodes.tdd as tdd_module

        with patch.object(tdd_module, "dispatch", AsyncMock(return_value=outcome)):
            result = await app.ainvoke(
                _ts("ready", ticket_body="Write a hello world function"),
                {"configurable": {"thread_id": "TICK-2"}},
            )

        assert result["status"] == "blocked"
        assert result["blocked_reason"].startswith("agent:")
        assert "utils.validators" in result["blocked_reason"]

        messages = [r.message for r in caplog.records]
        assert any("blocked, reason: agent:" in m for m in messages)
