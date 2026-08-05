from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    image: str
    workspace_path: str
    skills_path: str
    runtime: str = "runsc"
    workspace_mode: str = "ro"
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 300
    mem_limit: str = "512m"
    cpu_count: int = 2
    network: str = ""
    http_proxy: str = "http://172.17.0.1:8080"
    https_proxy: str = "http://172.17.0.1:8080"
    no_proxy: str = "localhost,127.0.0.1"


@dataclass
class SandboxSession:
    container_id: str
    port: int
    base_url: str
