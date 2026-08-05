import logging
from datetime import datetime, timezone

import docker
from docker.models.containers import Container

from bp_agents.platform.sandbox.base import Sandbox
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession
from bp_agents.platform.sandbox.egress import EgressPolicy

logger = logging.getLogger(__name__)

_DOCKER_LABEL_PREFIX = "bp_agents.sandbox"


def _label(key: str) -> str:
    return f"{_DOCKER_LABEL_PREFIX}.{key}"


class DockerSandbox(Sandbox):
    def __init__(
        self,
        docker_url: str = "unix://var/run/docker.sock",
        docker_client: docker.DockerClient | None = None,
        egress_policy: EgressPolicy | None = None,
    ):
        self._client = docker_client or docker.DockerClient(base_url=docker_url)
        self._egress_policy = egress_policy or EgressPolicy()
        self._egress_policy.log_allowlist()

    @property
    def egress_policy(self) -> EgressPolicy:
        return self._egress_policy

    async def create(self, config: SandboxConfig) -> SandboxSession:
        env = self._build_env(config)
        labels = self._build_labels(config)
        container = await self._create_and_start_container(config, env, labels)
        port = self._extract_port(container)
        base_url = f"http://localhost:{port}"

        return SandboxSession(
            container_id=container.id,
            port=port,
            base_url=base_url,
        )

    @staticmethod
    def _build_env(config: SandboxConfig) -> dict[str, str]:
        env = dict(config.env)
        env.setdefault("HTTP_PROXY", config.http_proxy)
        env.setdefault("HTTPS_PROXY", config.https_proxy)
        env.setdefault("NO_PROXY", config.no_proxy)
        return env

    @staticmethod
    def _build_labels(config: SandboxConfig) -> dict[str, str]:
        return {
            _label("image"): config.image,
            _label("created"): datetime.now(timezone.utc).isoformat(),
        }

    async def _create_and_start_container(
        self,
        config: SandboxConfig,
        env: dict[str, str],
        labels: dict[str, str],
    ) -> Container:
        create_kwargs: dict = dict(
            image=config.image,
            command=["sleep", str(config.timeout_seconds)],
            environment=env,
            labels=labels,
            detach=True,
            ports={8080: None},
            mem_limit=config.mem_limit,
            nano_cpus=int(config.cpu_count * 1e9),
            network=config.network,
            volumes={
                config.workspace_path: {"bind": "/data/workspace", "mode": "ro"},
                config.skills_path: {"bind": "/data/skills", "mode": "ro"},
            },
        )

        if config.runtime == "runsc":
            create_kwargs["runtime"] = "runsc"

        try:
            container: Container = self._client.containers.create(**create_kwargs)
        except docker.errors.DockerException:
            if config.runtime == "runsc":
                logger.error(
                    "runsc runtime unavailable — gVisor isolation required by ADR-0002"
                )
                raise
            raise
        container.start()
        return container

    @staticmethod
    def _extract_port(container: Container) -> int:
        try:
            container.reload()
            ports_dict = (
                container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            )
            if isinstance(ports_dict, dict):
                for bindings in ports_dict.values():
                    if isinstance(bindings, list) and bindings:
                        return int(bindings[0].get("HostPort", 8080))
        except (KeyError, TypeError, IndexError, AttributeError):
            pass
        return 8080

    async def is_running(self, container_id: str) -> bool:
        try:
            container = self._client.containers.get(container_id)
            container.reload()
            return container.status == "running"
        except docker.errors.NotFound:
            return False

    async def destroy(self, container_id: str) -> None:
        try:
            container = self._client.containers.get(container_id)
            container.remove(force=True, v=True)
        except docker.errors.NotFound:
            pass

    async def list_containers(self, label_filter: dict[str, str]) -> list[str]:
        filters = [
            f"{_DOCKER_LABEL_PREFIX}.{key}={value}"
            for key, value in label_filter.items()
        ]
        containers = self._client.containers.list(filters={"label": filters})
        return [c.id for c in containers]


GVisorSandbox = DockerSandbox
