from abc import ABC, abstractmethod

from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession


class Sandbox(ABC):
    @abstractmethod
    async def create(self, config: SandboxConfig) -> SandboxSession: ...

    @abstractmethod
    async def is_running(self, container_id: str) -> bool: ...

    @abstractmethod
    async def destroy(self, container_id: str) -> None: ...

    @abstractmethod
    async def exec_run(self, container_id: str, cmd: str) -> tuple[int, bytes]: ...
