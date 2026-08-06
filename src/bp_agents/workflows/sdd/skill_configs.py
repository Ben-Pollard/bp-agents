from bp_agents.platform.agent_config import AgentConfig

SKILL_CONFIGS: dict[str, AgentConfig] = {
    "tdd": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
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
        mcps={},
    ),
    "code_review": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
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
        mcps={},
    ),
    "revision": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
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
        mcps={},
    ),
    "minimizing_code": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={
            "read": {"*": "allow"},
            "edit": {"*": "deny"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": False,
            "task": False,
            "webfetch": False,
        },
        mcps={},
    ),
    "behavioral_verify": AgentConfig(
        model="openrouter/anthropic/claude-sonnet-4",
        provider="openrouter",
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
        },
        tools={
            "bash": True,
            "read": True,
            "task": False,
            "webfetch": False,
        },
        mcps={"playwright": True},
    ),
    "deterministic_gate": AgentConfig(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={
            "read": {"*": "allow"},
            "bash": {"*": "allow"},
        },
        tools={
            "bash": True,
            "read": True,
            "edit": False,
            "task": False,
        },
        mcps={},
    ),
}
