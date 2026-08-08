import logging
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.workflows.sdd.graph import build_ticket_pipeline
from bp_agents.workflows.sdd.state import TicketPipelineState


def _ts(
    status: str,
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
        "review_approved": None,
        "verification_passed": None,
        "blocked_reason": blocked_reason,
    }


@pytest.fixture
def target_repo() -> Path:
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
def skills_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "tdd.md").write_text("# TDD skill")
    return tmp


@pytest.fixture
def mock_sandbox() -> MagicMock:
    sandbox = MagicMock()
    sandbox.create = AsyncMock(
        return_value=SandboxSession(
            container_id="c1", port=32768, base_url="http://localhost:32768"
        )
    )
    sandbox.destroy = AsyncMock()
    return sandbox


@pytest.mark.asyncio
async def test_tdd_pipeline_wired_dispatch_logs_contracts(
    target_repo: Path,
    skills_dir: Path,
    mock_sandbox: MagicMock,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (target_repo / "hello.py").write_text("def hello():\n    return 'hello world'\n")
    outcome = {
        "status": "DONE",
        "summary": "Implemented hello world",
        "test_results": {"passed": 3, "failed": 0, "skipped": 0},
        "concerns": [],
    }

    fake_dispatch = AsyncMock(return_value=outcome)

    import bp_agents.workflows.sdd.nodes.tdd as tdd_module

    monkeypatch.setattr(tdd_module, "dispatch", fake_dispatch)

    app = build_ticket_pipeline(
        sandbox=mock_sandbox,
        sandbox_config=SandboxConfig(
            image="symphony-agent:latest",
            workspace_path=str(target_repo),
            skills_path=str(skills_dir),
            runtime="",
        ),
        target_repo_path=str(target_repo),
        skills_path=str(skills_dir),
    )

    caplog.set_level(logging.INFO)

    result = await app.ainvoke(
        _ts("ready", ticket_body="Write a hello world function"),
        {"configurable": {"thread_id": "TICK-1"}},
    )

    assert result["tdd_output"]["status"] == "DONE"

    messages = [r.message for r in caplog.records]

    assert any(
        "dispatching tdd" in m for m in messages
    ), "Expected 'dispatching tdd' log message (AC-01)"

    input_contract_lines = [
        m for m in messages if "dispatching tdd" in m and "contract=" in m
    ]
    assert input_contract_lines, "Input contract must be logged (AC-14)"
    contract_text = input_contract_lines[0]
    assert "tdd" in contract_text, "Input contract must contain skill name"

    assert any(
        "tdd output" in m for m in messages
    ), "Output contract must be logged (AC-15)"

    output_contract_lines = [
        m for m in messages if "tdd output" in m and "contract=" in m
    ]
    assert output_contract_lines, "Output contract must be logged (AC-15)"

    assert any(
        "implementing -> awaiting-review" in m for m in messages
    ), "TDD agent complete must transition to awaiting_review (AC-02)"

    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=target_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        "feat(TICK-1)" in log.stdout
    ), "Orchestrator must commit agent changes (AC-02)"

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=target_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        branch.stdout.strip() == "feat/tick-1"
    ), "Feature branch must be created (AC-02)"


@pytest.mark.asyncio
async def test_tdd_pipeline_wired_blocked_logs_reason(
    target_repo: Path,
    skills_dir: Path,
    mock_sandbox: MagicMock,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    outcome = {
        "status": "BLOCKED",
        "summary": "Missing dependency",
        "test_results": {"passed": 0, "failed": 0, "skipped": 0},
        "concerns": ["Module utils.validators not yet implemented"],
    }

    fake_dispatch = AsyncMock(return_value=outcome)

    import bp_agents.workflows.sdd.nodes.tdd as tdd_module

    monkeypatch.setattr(tdd_module, "dispatch", fake_dispatch)

    app = build_ticket_pipeline(
        sandbox=mock_sandbox,
        sandbox_config=SandboxConfig(
            image="symphony-agent:latest",
            workspace_path=str(target_repo),
            skills_path=str(skills_dir),
            runtime="",
        ),
        target_repo_path=str(target_repo),
        skills_path=str(skills_dir),
    )

    caplog.set_level(logging.INFO)

    result = await app.ainvoke(
        _ts("ready", ticket_body="Write a hello world function"),
        {"configurable": {"thread_id": "TICK-2"}},
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"].startswith("agent:")
    assert "utils.validators" in result["blocked_reason"]

    messages = [r.message for r in caplog.records]
    assert any(
        "blocked, reason: agent:" in m for m in messages
    ), "Blocked reason must be logged (AC-11)"

    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=target_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        "feat(TICK-2)" not in log.stdout
    ), "No commit should be made on blocked (AC-11)"


@pytest.mark.asyncio
async def test_tdd_pipeline_stub_routes_without_sandbox_config(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = build_ticket_pipeline()
    caplog.set_level(logging.INFO)

    result = await app.ainvoke(
        _ts("ready", ticket_body="Write a hello world function"),
        {"configurable": {"thread_id": "TICK-3"}},
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] is not None
    assert "BP_TARGET_REPO_PATH" in result["blocked_reason"]

    messages = [r.message for r in caplog.records]
    assert any(
        "blocked, reason:" in m for m in messages
    ), "Stub pipeline should block with a reason"

    tdd_msgs = [m for m in messages if "dispatching tdd" in m]
    assert not tdd_msgs, "Stub pipeline should NOT dispatch TDD"
