from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bp_agents.platform.sandbox import Sandbox
from bp_agents.platform.sandbox.config import (
    WORKSPACE_MOUNT_PATH,
    SandboxConfig,
    SandboxSession,
)
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox


def test_sandbox_is_abstract() -> None:
    with pytest.raises(TypeError):
        Sandbox()  # type: ignore[abstract]


def test_sandbox_has_abstract_methods() -> None:
    methods = ["create", "destroy"]
    for m in methods:
        assert hasattr(Sandbox, m)
        assert getattr(Sandbox, m).__isabstractmethod__


def test_sandbox_config_defaults() -> None:
    config = SandboxConfig(
        image="img",
        workspace_path="/w",
        skills_path="/s",
    )
    assert config.runtime == "runsc"
    assert config.timeout_seconds == 300
    assert config.mem_limit == "512m"
    assert config.cpu_count == 2
    assert config.network == ""
    assert config.workspace_mode == "ro"


def test_sandbox_config_writable_workspace() -> None:
    config = SandboxConfig(
        image="img",
        workspace_path="/w",
        skills_path="/s",
        workspace_mode="rw",
    )
    assert config.workspace_mode == "rw"


def test_sandbox_config_custom_network() -> None:
    config = SandboxConfig(
        image="img",
        workspace_path="/w",
        skills_path="/s",
        network="custom_net",
    )
    assert config.network == "custom_net"


def test_sandbox_session_fields() -> None:
    session = SandboxSession(
        container_id="abc",
        port=8080,
        base_url="http://172.17.0.1:8080",
    )
    assert session.container_id == "abc"
    assert session.port == 8080
    assert session.base_url == "http://172.17.0.1:8080"


class TestDockerSandbox:
    """Tests for DockerSandbox — uses injected mock client."""

    @pytest.fixture
    def sandbox_config(self) -> SandboxConfig:
        return SandboxConfig(
            image="test-image:latest",
            workspace_path="/tmp/workspace",
            skills_path="/tmp/skills",
            runtime="",
            env={"OPENCODE_PORT": "8080"},
            timeout_seconds=60,
            mem_limit="256m",
            cpu_count=1,
        )

    @pytest.fixture
    def mock_docker_client(self) -> MagicMock:
        client = MagicMock()
        client.api.create_host_config.return_value = {}
        return client

    @pytest.fixture
    def sandbox(self, mock_docker_client: MagicMock) -> DockerSandbox:
        return DockerSandbox(docker_client=mock_docker_client)

    @pytest.fixture
    def sandbox_config_with_network(self) -> SandboxConfig:
        return SandboxConfig(
            image="test-image:latest",
            workspace_path="/tmp/workspace",
            skills_path="/tmp/skills",
            runtime="",
            network="my-custom-network",
        )

    async def test_create_returns_session_with_container_id(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "abc123"
        mock_docker_client.containers.create.return_value = fake_container

        session = await sandbox.create(sandbox_config)

        assert session.container_id == "abc123"

    async def test_destroy_removes_container(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        fake_container = MagicMock()
        mock_docker_client.containers.get.return_value = fake_container

        await sandbox.destroy("abc123")

        fake_container.remove.assert_called_once_with(force=True, v=True)

    async def test_destroy_ignores_missing_container(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        import docker

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound(
            "not found", response=MagicMock(status_code=404)
        )

        await sandbox.destroy("abc123")

    async def test_create_sets_env_with_proxy_defaults(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        _call_env = mock_docker_client.containers.create.call_args[1].get(
            "environment", {}
        )
        assert _call_env["HTTP_PROXY"] == "http://172.17.0.1:8080"
        assert _call_env["HTTPS_PROXY"] == "http://172.17.0.1:8080"
        assert _call_env["NO_PROXY"] == "localhost,127.0.0.1"
        assert _call_env["OPENCODE_PORT"] == "8080"

    async def test_create_sets_env_with_custom_proxies(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        sandbox_config.http_proxy = "http://custom-proxy:3128"
        sandbox_config.https_proxy = "http://custom-proxy:3128"
        sandbox_config.no_proxy = "localhost,127.0.0.1,.internal"
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        _call_env = mock_docker_client.containers.create.call_args[1].get(
            "environment", {}
        )
        assert _call_env["HTTP_PROXY"] == "http://custom-proxy:3128"
        assert _call_env["HTTPS_PROXY"] == "http://custom-proxy:3128"
        assert _call_env["NO_PROXY"] == "localhost,127.0.0.1,.internal"

    async def test_create_passes_runtime_when_runsc(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        sandbox_config.runtime = "runsc"
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        assert (
            mock_docker_client.containers.create.call_args[1].get("runtime") == "runsc"
        )

    async def test_create_omits_runtime_when_empty(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        assert "runtime" not in mock_docker_client.containers.create.call_args[1]

    async def test_create_raises_when_runsc_unavailable(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        import docker

        sandbox_config.runtime = "runsc"
        mock_docker_client.containers.create.side_effect = (
            docker.errors.DockerException("runsc not available")
        )

        with pytest.raises(docker.errors.DockerException):
            await sandbox.create(sandbox_config)

    async def test_create_raises_when_non_runsc_fails(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        import docker

        mock_docker_client.containers.create.side_effect = (
            docker.errors.DockerException("some other error")
        )

        with pytest.raises(docker.errors.DockerException):
            await sandbox.create(sandbox_config)

    async def test_create_sets_binds_and_resources(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert call_kwargs["mem_limit"] == "256m"
        assert call_kwargs["nano_cpus"] == int(1 * 1e9)
        volumes = call_kwargs["volumes"]
        assert volumes["/tmp/workspace"] == {"bind": WORKSPACE_MOUNT_PATH, "mode": "ro"}
        assert volumes["/tmp/skills"] == {"bind": "/data/skills", "mode": "ro"}

    async def test_create_uses_writable_workspace_mode_when_configured(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        sandbox_config.workspace_mode = "rw"
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        volumes = mock_docker_client.containers.create.call_args[1]["volumes"]
        assert volumes["/tmp/workspace"] == {"bind": WORKSPACE_MOUNT_PATH, "mode": "rw"}

    async def test_create_sets_labels(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        labels = mock_docker_client.containers.create.call_args[1].get("labels", {})
        assert labels["bp_agents.sandbox.image"] == "test-image:latest"
        assert "bp_agents.sandbox.created" in labels

    async def test_create_uses_config_network(
        self,
        sandbox_config_with_network: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        """Container created directly on configured network — no post-creation
        network.connect() call (avoids gVisor runsc secondary-network bug)."""
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config_with_network)

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert call_kwargs["network"] == "my-custom-network"
        mock_docker_client.networks.get.assert_not_called()
        mock_docker_client.networks.connect.assert_not_called()

    async def test_create_extracts_ip_from_configured_network(
        self,
        sandbox_config_with_network: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        """When created on a configured network, the container's IP on that
        network is used for the session base_url."""
        fake_container = MagicMock()
        fake_container.id = "c1"
        fake_container.attrs = {
            "NetworkSettings": {
                "Networks": {"my-custom-network": {"IPAddress": "10.99.0.42"}}
            }
        }
        mock_docker_client.containers.create.return_value = fake_container

        session = await sandbox.create(sandbox_config_with_network)

        assert session.base_url == "http://10.99.0.42:8080"
        assert session.port == 8080

    async def test_create_passes_ports_to_create(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        ports = mock_docker_client.containers.create.call_args[1].get("ports", [])
        assert 8080 in ports

    async def test_create_passes_port_mapping(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config)

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert "ports" in call_kwargs
        assert call_kwargs["ports"] == {8080: None}

    async def test_create_extracts_port_from_container(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        fake_container.attrs = {
            "NetworkSettings": {
                "Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}
            }
        }
        mock_docker_client.containers.create.return_value = fake_container

        session = await sandbox.create(sandbox_config)

        assert session.port == 32768
        assert session.base_url == "http://172.17.0.1:32768"

    async def test_create_falls_back_to_default_port(
        self,
        sandbox_config: SandboxConfig,
        mock_docker_client: MagicMock,
        sandbox: DockerSandbox,
    ) -> None:
        fake_container = MagicMock()
        fake_container.id = "c1"
        fake_container.attrs = {}
        mock_docker_client.containers.create.return_value = fake_container

        session = await sandbox.create(sandbox_config)

        assert session.port == 8080
        assert session.base_url == "http://172.17.0.1:8080"

    def test_e2e_python_one_liner_is_valid_syntax(self) -> None:
        """The E2E test for blocked internet (AC-22) uses a single-line
        Python one-liner passed to python -c via exec_run. This test
        ensures the Python code is syntactically valid so the E2E test
        actually exercises the proxy rather than failing on a parse error."""
        code = (
            "import urllib.request, urllib.error;"
            "r = urllib.request.urlopen('https://example.com', timeout=10);"
            "print('REACHED', r.status)"
        )
        compile(code, "<test>", "exec")
