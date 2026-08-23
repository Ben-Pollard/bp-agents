from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import docker
import pytest
import yaml

from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox


def _load_compose() -> dict:
    root = Path(__file__).resolve().parents[3]
    return yaml.safe_load((root / "docker-compose.yml").read_text())


def test_compose_egress_proxy_enforces_allowlist() -> None:
    """The mitmproxy egress proxy must be configured with a blocking addon
    script so arbitrary internet is not reachable (AC-21/AC-22)."""
    compose = _load_compose()
    command = compose["services"]["egress-proxy"]["command"]
    command_str = " ".join(command) if isinstance(command, list) else command
    assert "-s" in command_str, "egress-proxy must have an addon script"
    assert "egress_blocker.py" in command_str, "addon script must be egress_blocker.py"


def test_compose_allowlist_covers_default_allowlist() -> None:
    """The egress blocker addon script must define a non-empty
    DEFAULT_ALLOWLIST so arbitrary internet is not reachable (AC-21/AC-22)."""
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    assert "DEFAULT_ALLOWLIST = [" in script
    assert "api.openai.com" in script


def test_egress_blocker_logs_ticket_unknown_suffix() -> None:
    """AC-3/AC-22: The egress blocker addon script must log blocked egress
    with a 'from ticket <id>' suffix. Since the proxy has no ticket context,
    the placeholder 'from ticket <unknown>' is used so the log format matches
    the acceptance criteria."""
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    assert (
        "from ticket <unknown>" in script
    ), "egress_blocker.py must log 'from ticket <unknown>' suffix"


def _load_sandbox_dockerfile() -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "Dockerfile.sandbox").read_text()


def test_sandbox_dockerfile_installs_opencode_via_npm() -> None:
    """The sandbox image installs opencode from the npm package
    `opencode-ai`. Installing via `uv tool install opencode@latest` fails
    because opencode is not published to PyPI, which blocks the entire TDD
    pipeline (QA finding)."""
    dockerfile = _load_sandbox_dockerfile()
    assert (
        "npm install -g opencode-ai" in dockerfile
    ), "Dockerfile.sandbox must install opencode via npm package opencode-ai"
    assert (
        "uv tool install opencode" not in dockerfile
    ), "Dockerfile.sandbox must NOT install opencode from PyPI via uv"
    assert (
        "nodejs" in dockerfile
    ), "Dockerfile.sandbox must install nodejs before running npm install"


def test_sandbox_dockerfile_serves_with_hostname_flag() -> None:
    """The opencode serve command uses --hostname, not --host."""
    dockerfile = _load_sandbox_dockerfile()
    assert "--hostname" in dockerfile, "opencode serve must use --hostname flag"
    assert (
        '"opencode", "serve"' in dockerfile
    ), "Dockerfile.sandbox must run `opencode serve`"


def test_compose_orchestrator_has_target_repo_default() -> None:
    """The orchestrator service must default BP_TARGET_REPO_PATH to a real
    path so the live system runs the real TDD pipeline instead of falling
    back to the stub (QA finding)."""
    compose = _load_compose()
    env = compose["services"]["orchestrator"]["environment"]
    target = env["BP_TARGET_REPO_PATH"]
    assert "${BP_TARGET_REPO_PATH:-/dev/null}" not in target
    assert "${BP_TARGET_REPO_PATH:-" in target
    default = target.split(":-", 1)[1].rstrip("}")
    assert default, "BP_TARGET_REPO_PATH default must not be empty"
    assert default != "/dev/null"


def test_egress_blocker_reads_env_var() -> None:
    """The egress blocker addon script must read the allowlist from the
    MITMPROXY_ALLOWLIST environment variable (comma-separated), falling back
    to DEFAULT_ALLOWLIST when the env var is not set. This verifies the
    config mechanism required by AC-21."""
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    assert 'os.environ.get("MITMPROXY_ALLOWLIST")' in script or (
        'os.getenv("MITMPROXY_ALLOWLIST")' in script
    ), "egress_blocker.py must read MITMPROXY_ALLOWLIST env var"
    assert (
        "DEFAULT_ALLOWLIST" in script
    ), "egress_blocker.py must define DEFAULT_ALLOWLIST as fallback"


def test_sandbox_lifecycle_with_policy() -> None:
    """Pipeline-level: create, destroy with an
    injected docker client, exercising the same path the orchestrator uses."""
    client = MagicMock()
    client.api.create_host_config.return_value = {}

    container = MagicMock()
    container.id = "sandbox-abc"
    container.attrs = {}
    client.containers.create.return_value = container

    sandbox = DockerSandbox(docker_client=client)

    config = SandboxConfig(
        image="opencode-agent:latest",
        workspace_path="/tmp/ws",
        skills_path="/tmp/skills",
        runtime="runsc",
    )

    session = _run(sandbox.create(config))
    assert session.container_id == "sandbox-abc"

    assert "runsc" == client.containers.create.call_args[1]["runtime"]
    assert "network" not in client.containers.create.call_args[1]

    client.containers.get.return_value = container
    _run(sandbox.destroy(session.container_id))
    container.remove.assert_called_once_with(force=True, v=True)


def test_runsc_unavailable_raises_not_falls_back() -> None:
    """ADR-0002 requires gVisor. If runsc is unavailable the sandbox must
    fail rather than silently drop isolation."""
    client = MagicMock()
    client.api.create_host_config.return_value = {}
    client.containers.create.side_effect = docker.errors.DockerException(
        "runsc not available"
    )
    sandbox = DockerSandbox(docker_client=client)

    config = SandboxConfig(
        image="opencode-agent:latest",
        workspace_path="/tmp/ws",
        skills_path="/tmp/skills",
        runtime="runsc",
    )

    with pytest.raises(docker.errors.DockerException):
        _run(sandbox.create(config))
    assert client.containers.create.call_count == 1


def _container_with_status(status: str) -> MagicMock:
    c = MagicMock()
    c.status = status
    return c


def _run(coro):
    import asyncio

    return asyncio.run(coro)
