from dataclasses import dataclass


@dataclass
class AgentConfig:
    model: str
    provider: str
    permissions: dict
    tools: dict[str, bool]
    mcps: dict[str, bool]


def to_opencode_json(config: AgentConfig, provider_defs: dict, mcp_defs: dict) -> dict:
    result: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": provider_defs,
        "permission": config.permissions,
        "mcp": {},
    }
    for mcp_name, enabled in config.mcps.items():
        if enabled and mcp_name in mcp_defs:
            merged = dict(mcp_defs[mcp_name])
            merged["enabled"] = True
            result["mcp"][mcp_name] = merged
    return result
