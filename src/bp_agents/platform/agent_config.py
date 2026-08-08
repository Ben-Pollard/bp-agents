from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentConfig:
    model: str
    provider: str
    permissions: dict
    tools: dict[str, bool]
    mcps: dict[str, bool]


def to_opencode_json(
    config: AgentConfig,
    provider_defs: dict,
    mcp_defs: dict,
    skills_path: str = "",
    otel_enabled: bool = True,
    plugins: list[str] | None = None,
) -> dict:
    result: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": provider_defs,
        "permission": config.permissions,
        "mcp": mcp_defs,
    }
    if plugins:
        result["plugin"] = plugins
    if otel_enabled:
        result["experimental"] = {"openTelemetry": True}
    if skills_path and Path(skills_path).is_dir():
        skills_map = {}
        for d in sorted(Path(skills_path).iterdir()):
            if d.is_dir() and (d / "SKILL.md").is_file():
                skills_map[d.name] = f"/data/skills/{d.name}/SKILL.md"
        if skills_map:
            result["skills"] = skills_map
    return result
