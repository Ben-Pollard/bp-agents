from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentConfig:
    model: str
    provider: str
    permissions: dict
    tools: dict[str, bool]
    mcps: dict[str, bool]


_SANDBOX_SKILLS_MOUNT = "/data/skills"


def to_opencode_json(
    config: AgentConfig,
    provider_defs: dict,
    mcp_defs: dict,
    skills_path: str = "",
    otel_enabled: bool = True,
) -> dict:
    result: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": provider_defs,
        "permission": config.permissions,
        "mcp": {},
    }
    if otel_enabled:
        result["experimental"] = {"openTelemetry": True}
    if skills_path and Path(skills_path).is_dir():
        result["skills"] = [_SANDBOX_SKILLS_MOUNT]
    return result
