import logging
from datetime import datetime, timezone

import docker
from docker.models.containers import Container

from bp_agents.platform.sandbox.base import Sandbox
from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession

logger = logging.getLogger(__name__)

_DOCKER_LABEL_PREFIX = "bp_agents.sandbox"


def _label(key: str) -> str:
    return f"{_DOCKER_LABEL_PREFIX}.{key}"


class DockerSandbox(Sandbox):
    def __init__(
        self,
        docker_url: str = "unix://var/run/docker.sock",
        docker_client: docker.DockerClient | None = None,
    ):
        self._client = docker_client or docker.DockerClient(base_url=docker_url)

    async def create(self, config: SandboxConfig) -> SandboxSession:
        env = dict(config.env)
        env.setdefault("HTTP_PROXY", config.http_proxy)
        env.setdefault("HTTPS_PROXY", config.https_proxy)
        env.setdefault("NO_PROXY", config.no_proxy)

        labels = {
            _label("image"): config.image,
            _label("created"): datetime.now(timezone.utc).isoformat(),
        }

        host_config = self._client.api.create_host_config(
            binds=[
                f"{config.workspace_path}:/data/workspace:ro",
                f"{config.skills_path}:/data/skills:ro",
            ],
            mem_limit=config.mem_limit,
            nano_cpus=int(config.cpu_count * 1e9),
            network_mode="bp_agents",
        )

        create_kwargs: dict = dict(
            image=config.image,
            command=["sleep", str(config.timeout_seconds)],
            environment=env,
            host_config=host_config,
            labels=labels,
            detach=True,
        )

        if config.runtime == "runsc":
            create_kwargs["runtime"] = "runsc"

        try:
            container: Container = self._client.containers.create(**create_kwargs)
        except docker.errors.DockerException:
            if config.runtime == "runsc":
                logger.warning(
                    "runsc runtime unavailable, falling back to default runtime"
                )
                create_kwargs.pop("runtime", None)
                container = self._client.containers.create(**create_kwargs)
            else:
                raise
        container.start()

        # Inspect to find exposed port
        container.reload()
        port = 8080  # default opencode serve port
        base_url = f"http://localhost:{port}"

        return SandboxSession(
            container_id=container.id,
            port=port,
            base_url=base_url,
        )

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
        filters = {}
        for key, value in label_filter.items():
            filters[f"{_DOCKER_LABEL_PREFIX}.{key}"] = value
        containers = self._client.containers.list(filters={"label": filters})
        return [c.id for c in containers]
