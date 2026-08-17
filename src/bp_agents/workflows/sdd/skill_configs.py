from bp_agents.platform.agent_config import AgentConfig


def _skill_config(
    model: str = "openrouter/deepseek/deepseek-v4-flash",
    provider: str = "openrouter",
    permissions: dict | None = None,
    tools: dict[str, bool] | None = None,
    mcps: dict[str, bool] | None = None,
) -> AgentConfig:
    return AgentConfig(
        model=model,
        provider=provider,
        permissions=permissions or {},
        tools=tools or {},
        mcps=mcps or {},
    )


SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": _skill_config(
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
            "edit": {"*": "allow"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": True,
            "task": False,
            "webfetch": False,
        },
    ),
    "requesting-code-review": _skill_config(
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
            "edit": {"*": "deny"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": False,
            "task": False,
            "webfetch": False,
        },
    ),
    "receiving-code-review": _skill_config(
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
            "edit": {"*": "allow"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": True,
            "task": False,
            "webfetch": False,
        },
    ),
    "qa": _skill_config(
        model="openrouter/anthropic/claude-sonnet-4",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "task": False, "webfetch": False},
        mcps={"playwright": True},
    ),
    "minimizing-code": _skill_config(
        permissions={"read": {"*": "allow"}, "edit": {"*": "deny"}},
        tools={
            "bash": True,
            "read": True,
            "edit": False,
            "task": False,
            "webfetch": False,
        },
    ),
}
