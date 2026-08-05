from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import docker
import pytest
import yaml

from bp_agents.platform.sandbox.config import SandboxConfig
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.platform.sandbox.egress import EgressBlockedError, EgressPolicy


def _load_compose() -> dict:
    root = Path(__file__).resolve().parents[2]
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
    """Every host in the EgressPolicy default allowlist must be present in
    the egress blocker addon script's DEFAULT_ALLOWLIST, otherwise a
    permitted destination would be blocked by the proxy while the policy
    permits it."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    script_hosts = set()
    in_default = False
    for line in script.splitlines():
        stripped = line.strip()
        if stripped == "DEFAULT_ALLOWLIST = [":
            in_default = True
            continue
        if in_default:
            if stripped == "]":
                break
            if stripped.startswith('"') and stripped.endswith('",'):
                host = stripped.strip('",')
                script_hosts.add(host)

    default_hosts = set(EgressPolicy().allowlist)
    assert (
        default_hosts <= script_hosts
    ), f"missing in egress_blocker.py DEFAULT_ALLOWLIST: {default_hosts - script_hosts}"


def test_egress_blocker_logs_ticket_unknown_suffix() -> None:
    """AC-3/AC-22: The egress blocker addon script must log blocked egress
    with a 'from ticket <id>' suffix. Since the proxy has no ticket context,
    the placeholder 'from ticket <unknown>' is used so the log format matches
    the acceptance criteria."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    assert (
        "from ticket <unknown>" in script
    ), "egress_blocker.py must log 'from ticket <unknown>' suffix"


def test_egress_blocker_reads_env_var() -> None:
    """The egress blocker addon script must read the allowlist from the
    MITMPROXY_ALLOWLIST environment variable (comma-separated), falling back
    to DEFAULT_ALLOWLIST when the env var is not set. This verifies the
    config mechanism required by AC-21."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "egress_blocker.py").read_text()
    assert 'os.environ.get("MITMPROXY_ALLOWLIST")' in script or (
        'os.getenv("MITMPROXY_ALLOWLIST")' in script
    ), "egress_blocker.py must read MITMPROXY_ALLOWLIST env var"
    assert (
        "DEFAULT_ALLOWLIST" in script
    ), "egress_blocker.py must define DEFAULT_ALLOWLIST as fallback"


@pytest.fixture
def egress_policy() -> EgressPolicy:
    return EgressPolicy()


def test_policy_blocks_arbitrary_internet(
    egress_policy: EgressPolicy,
) -> None:
    with pytest.raises(EgressBlockedError):
        egress_policy.check("https://example.com", ticket_id="hello-1")


def test_policy_permits_pypi_and_llm(
    egress_policy: EgressPolicy,
) -> None:
    egress_policy.check("https://pypi.org/simple/", ticket_id="hello-1")
    egress_policy.check("https://api.openai.com/v1/chat", ticket_id="hello-1")


def test_sandbox_lifecycle_with_policy() -> None:
    """Pipeline-level: create, is_running, list_containers, destroy with an
    injected docker client, exercising the same path the orchestrator uses."""
    client = MagicMock()
    client.api.create_host_config.return_value = {}

    container = MagicMock()
    container.id = "sandbox-abc"
    container.attrs = {}
    client.containers.create.return_value = container

    sandbox = DockerSandbox(docker_client=client, egress_policy=EgressPolicy())

    config = SandboxConfig(
        image="symphony-agent:latest",
        workspace_path="/tmp/ws",
        skills_path="/tmp/skills",
        runtime="runsc",
    )

    session = _run(sandbox.create(config))
    assert session.container_id == "sandbox-abc"

    assert "runsc" == client.containers.create.call_args[1]["runtime"]
    assert "network" not in client.containers.create.call_args[1]

    client.containers.get.return_value = _container_with_status("running")
    assert _run(sandbox.is_running(session.container_id)) is True

    client.containers.list.return_value = [container]
    listed = _run(sandbox.list_containers({"image": "symphony-agent:latest"}))
    assert listed == ["sandbox-abc"]

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
        image="symphony-agent:latest",
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
