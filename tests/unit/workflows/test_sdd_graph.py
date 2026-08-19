import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.graph import END

from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.workflows.sdd.graph import (
    build_ticket_pipeline,
    route_ticket,
)
from tests.conftest import ts_ready


def test_build_ticket_pipeline_compiles() -> None:
    app = build_ticket_pipeline()
    assert app is not None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ready", "implement"),
        ("implementing", "implement"),
        ("awaiting_review", "review"),
        ("reviewing", "review"),
        ("awaiting_revision", "revise"),
        ("revising", "revise"),
        ("awaiting_verification", "verify"),
        ("verifying", "verify"),
        ("awaiting_approval", END),
        ("done", END),
        ("blocked", END),
    ],
)
def test_route_ticket_returns_next_node(status: str, expected: str) -> None:
    assert route_ticket(ts_ready(status)) == expected


def test_route_ticket_returns_block_when_blocked_reason() -> None:
    assert route_ticket(ts_ready("ready", blocked_reason="blocking issue")) == "block"


def test_route_ticket_returns_block_when_blocked_reason_and_implementing() -> None:
    assert (
        route_ticket(ts_ready("implementing", blocked_reason="dep on API")) == "block"
    )


def test_route_ticket_ignores_blocked_reason_when_already_blocked() -> None:
    assert route_ticket(ts_ready("blocked", blocked_reason="still blocked")) == END


def test_pipeline_advances_ready_to_blocked_without_sandbox() -> None:
    app = build_ticket_pipeline()
    initial = ts_ready("ready")
    result = app.invoke(initial, {"configurable": {"thread_id": "TICK-1"}})
    assert result["status"] == "blocked"
    assert result["blocked_reason"] is not None
    assert "BP_TARGET_REPO_PATH" in result["blocked_reason"]


def test_pipeline_flow_from_awaiting_revision_without_sandbox() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-3"}}
    initial = ts_ready("awaiting_revision")
    result = app.invoke(initial, config)
    assert result["status"] == "blocked"


def test_pipeline_flow_from_awaiting_verification_without_sandbox() -> None:
    app = build_ticket_pipeline()
    config = {"configurable": {"thread_id": "TICK-4"}}
    initial = ts_ready("awaiting_verification")
    result = app.invoke(initial, config)
    assert result["status"] == "blocked"


class TestTddGraphWire:
    """Tracer bullet: ticket flows through the graph with a mocked AgentStageNode dispatch."""

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
        tdd_outcome = {
            "status": "DONE",
            "summary": "Implemented hello world",
            "test_results": {"passed": 3, "failed": 0, "skipped": 0},
            "concerns": [],
        }
        review_outcome = {
            "spec_compliance": True,
            "code_quality": {"SOLID": True, "DRY": True},
            "test_quality": {"tests.md": True},
            "operational": True,
            "violations": [],
            "review_notes": [],
            "action": "approved",
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

        async def _side_effect(*args, **kwargs):
            skill = kwargs.get("skill", "tdd")
            if skill == "tdd":
                return tdd_outcome
            if skill == "requesting-code-review":
                return review_outcome
            return {
                "status": "PASS",
                "stage_results": {},
                "failed_acs": [],
                "blocked_items": [],
                "discovered_blockers": [],
                "summary": "ok",
            }

        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        with patch.object(
            stage_module, "dispatch", AsyncMock(side_effect=_side_effect)
        ):
            result = await app.ainvoke(
                ts_ready("ready", ticket_body="Write a hello world function"),
                {"configurable": {"thread_id": "TICK-1"}},
            )

        assert result["tdd_output"].status == "DONE"
        assert result["review_output"].action == "approved"
        assert result["qa_output"].status == "PASS"
        assert result["status"] == "awaiting_approval"

        messages = [r.message for r in caplog.records]
        assert any("dispatching tdd" in m for m in messages)
        assert any("dispatching requesting-code-review" in m for m in messages)
        assert any("dispatching qa" in m for m in messages)
        assert any("tdd output" in m for m in messages)
        assert any("requesting-code-review output" in m for m in messages)
        assert any("qa output" in m for m in messages)

        log = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=target_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "feat(TICK-1)" in log.stdout or "tdd" in log.stdout

    async def test_ready_ticket_with_tdd_blocked_reaches_blocked(
        self,
        target_repo: Path,
        mock_sandbox: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        tdd_outcome = {
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

        import bp_agents.workflows.sdd.nodes.agent_stage as stage_module

        async def _side_effect(*args, **kwargs):
            return tdd_outcome

        with patch.object(
            stage_module, "dispatch", AsyncMock(side_effect=_side_effect)
        ):
            result = await app.ainvoke(
                ts_ready("ready", ticket_body="Write a hello world function"),
                {"configurable": {"thread_id": "TICK-2"}},
            )

        assert result["status"] == "blocked"
        assert result["blocked_reason"] is not None

        messages = [r.message for r in caplog.records]
        assert any("blocked, reason: agent:" in m for m in messages)
