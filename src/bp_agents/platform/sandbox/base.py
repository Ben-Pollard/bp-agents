from abc import ABC, abstractmethod

from bp_agents.platform.sandbox.config import SandboxConfig, SandboxSession


class Sandbox(ABC):
    @abstractmethod
    async def create(self, config: SandboxConfig) -> SandboxSession: ...

    @abstractmethod
    async def destroy(self, container_id: str) -> None: ...
