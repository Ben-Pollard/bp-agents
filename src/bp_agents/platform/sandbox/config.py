from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    image: str
    workspace_path: str
    skills_path: str
    runtime: str = "runsc"
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 300
    mem_limit: str = "512m"
    cpu_count: int = 2


@dataclass
class SandboxSession:
    container_id: str
    port: int
    base_url: str
