from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bp_agents.platform.sandbox import Sandbox
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.platform.sandbox.docker_sandbox import DockerSandbox
from bp_agents.platform.sandbox.egress import (
    DEFAULT_ALLOWLIST,
    EgressBlockedError,
    EgressPolicy,
)


def test_sandbox_is_abstract() -> None:
    with pytest.raises(TypeError):
        Sandbox()  # type: ignore[abstract]


def test_sandbox_has_abstract_methods() -> None:
    methods = ["create", "is_running", "destroy", "list_containers"]
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
        base_url="http://localhost:8080",
    )
    assert session.container_id == "abc"
    assert session.port == 8080
    assert session.base_url == "http://localhost:8080"


class TestEgressPolicy:
    def test_default_allowlist_includes_llm_endpoints(self) -> None:
        policy = EgressPolicy()
        assert policy.is_allowed("https://api.openai.com/v1/chat")
        assert policy.is_allowed("https://api.anthropic.com/v1/messages")
        assert policy.is_allowed("https://api.openrouter.ai/chat")

    def test_default_allowlist_includes_package_registries(self) -> None:
        policy = EgressPolicy()
        assert policy.is_allowed("https://pypi.org/simple/")
        assert policy.is_allowed("https://files.pythonhosted.org/packages/")
        assert policy.is_allowed("https://registry.npmjs.org/")

    def test_default_allowlist_includes_mcp_endpoints(self) -> None:
        policy = EgressPolicy()
        assert policy.is_allowed("https://api.context7.com/v1/query")
        assert policy.is_allowed("https://context7.com/")

    def test_arbitrary_internet_is_blocked(self) -> None:
        policy = EgressPolicy()
        assert not policy.is_allowed("https://example.com")
        assert not policy.is_allowed("https://google.com")
        assert not policy.is_allowed("https://github.com/")

    def test_git_remotes_are_blocked(self) -> None:
        policy = EgressPolicy()
        assert not policy.is_allowed("https://github.com/user/repo.git")
        assert not policy.is_allowed("git@github.com:user/repo.git")

    def test_check_raises_for_blocked_destination(self) -> None:
        policy = EgressPolicy()
        with pytest.raises(EgressBlockedError) as exc:
            policy.check("https://example.com")
        assert "blocked egress" in str(exc.value)
        assert exc.value.destination == "https://example.com"

    def test_check_passes_for_allowed_destination(self) -> None:
        policy = EgressPolicy()
        policy.check("https://api.openai.com/v1/chat")  # no error

    def test_logs_allowlist_on_startup(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        caplog.set_level(logging.INFO)
        allowed = ["custom.example.com"]
        EgressPolicy(allowlist=allowed)
        assert "egress allowlist" in caplog.text
        assert "custom.example.com" in caplog.text

    def test_log_allowlist_method(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        caplog.set_level(logging.INFO)
        policy = EgressPolicy(allowlist=["test.example.com"])
        caplog.clear()
        policy.log_allowlist()
        assert "egress allowlist" in caplog.text
        assert "test.example.com" in caplog.text

    def test_custom_allowlist(self) -> None:
        policy = EgressPolicy(allowlist=["my-internal-api.com"])
        assert policy.is_allowed("https://my-internal-api.com/data")
        assert not policy.is_allowed("https://api.openai.com")

    def test_subdomain_suffix_bypass_is_blocked(self) -> None:
        policy = EgressPolicy()
        assert not policy.is_allowed("https://evil-pypi.org.malicious.com")
        assert not policy.is_allowed("https://pypi.org.malicious.com")
        assert not policy.is_allowed("https://notpypi.org")

    def test_subdomain_of_allowed_host_is_allowed(self) -> None:
        policy = EgressPolicy()
        assert policy.is_allowed("https://sub.pypi.org/simple/")
        assert policy.is_allowed("https://api.openai.com/v1/chat")

    def test_non_url_destination_is_blocked(self) -> None:
        policy = EgressPolicy()
        assert not policy.is_allowed("not a url")
        assert not policy.is_allowed("")

    def test_default_allowlist_constant_not_mutable(self) -> None:
        assert "api.openai.com" in DEFAULT_ALLOWLIST


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

    async def test_git_commands_fail_in_sandbox(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        """Git is not available in the sandbox image.

        AC-23: Any attempt by an agent to run a git command SHALL fail.
        The sandbox image deliberately excludes git. DockerSandbox.exec_run
        surfaces the container-level exec failure.
        """
        fake_container = MagicMock()
        fake_container.exec_run.return_value = (1, b"git: command not found")
        mock_docker_client.containers.get.return_value = fake_container

        exit_code, output = await sandbox.exec_run("sandbox-1", "git status")
        assert exit_code != 0
        assert (
            b"command not found" in output
            or b"not found" in output.lower()
            or b"not a command" in output.lower()
            or b"no such file" in output.lower()
        )
        mock_docker_client.containers.get.assert_called_once_with("sandbox-1")
        fake_container.exec_run.assert_called_once_with("git status")

    async def test_exec_run_passes_shell_commands_with_redirects(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        """AC-2: exec_run must handle shell redirect syntax when wrapped in
        sh -c. docker-py's exec_run splits the string via shlex.split and
        passes tokens as positional args, so '2>&1' must be inside a shell
        invocation, not as a direct argument to the target command.
        """
        fake_container = MagicMock()
        fake_container.exec_run.return_value = (0, b"requests 2.32.0")
        mock_docker_client.containers.get.return_value = fake_container

        exit_code, output = await sandbox.exec_run(
            "sandbox-1",
            "sh -c 'pip install --dry-run requests 2>&1'",
        )
        assert exit_code == 0
        fake_container.exec_run.assert_called_once_with(
            "sh -c 'pip install --dry-run requests 2>&1'"
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

    async def test_is_running_returns_true_for_running_container(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        fake_container = MagicMock()
        fake_container.status = "running"
        mock_docker_client.containers.get.return_value = fake_container

        result = await sandbox.is_running("abc123")

        assert result is True

    async def test_is_running_returns_false_for_missing_container(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        import docker

        mock_docker_client.containers.get.side_effect = docker.errors.NotFound(
            "not found", response=MagicMock(status_code=404)
        )

        result = await sandbox.is_running("abc123")

        assert result is False

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

    async def test_list_containers_filters_by_label(
        self, mock_docker_client: MagicMock, sandbox: DockerSandbox
    ) -> None:
        c1, c2 = MagicMock(), MagicMock()
        c1.id = "id1"
        c2.id = "id2"
        mock_docker_client.containers.list.return_value = [c1, c2]

        result = await sandbox.list_containers({"image": "test-image:latest"})

        assert result == ["id1", "id2"]
        mock_docker_client.containers.list.assert_called_once_with(
            filters={"label": ["bp_agents.sandbox.image=test-image:latest"]}
        )

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
        assert volumes["/tmp/workspace"] == {"bind": "/data/workspace", "mode": "ro"}
        assert volumes["/tmp/skills"] == {"bind": "/data/skills", "mode": "ro"}

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
        fake_container = MagicMock()
        fake_container.id = "c1"
        mock_docker_client.containers.create.return_value = fake_container

        await sandbox.create(sandbox_config_with_network)

        call_kwargs = mock_docker_client.containers.create.call_args[1]
        assert call_kwargs["network"] == "my-custom-network"

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
        assert session.base_url == "http://localhost:32768"

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
        assert session.base_url == "http://localhost:8080"

    async def test_accepts_egress_policy(self, mock_docker_client: MagicMock) -> None:
        policy = EgressPolicy(allowlist=["custom-only.com"])
        sandbox = DockerSandbox(docker_client=mock_docker_client, egress_policy=policy)
        assert sandbox.egress_policy is policy

    async def test_default_egress_policy_created(
        self, mock_docker_client: MagicMock
    ) -> None:
        sandbox = DockerSandbox(docker_client=mock_docker_client)
        assert isinstance(sandbox.egress_policy, EgressPolicy)

    async def test_egress_policy_enforces_blocked_destinations(
        self, mock_docker_client: MagicMock
    ) -> None:
        sandbox = DockerSandbox(docker_client=mock_docker_client)
        with pytest.raises(EgressBlockedError):
            sandbox.egress_policy.check("https://example.com")

    async def test_egress_policy_allows_listed_destinations(
        self, mock_docker_client: MagicMock
    ) -> None:
        sandbox = DockerSandbox(docker_client=mock_docker_client)
        sandbox.egress_policy.check("https://api.openai.com/v1/chat")  # no error

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
