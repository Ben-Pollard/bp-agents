from pathlib import Path

from bp_agents.platform.agent_config import (
    _SANDBOX_SKILLS_MOUNT,
    AgentConfig,
    to_opencode_json,
)


def _config(**overrides) -> AgentConfig:
    base = dict(
        model="openrouter/deepseek/deepseek-v4-flash",
        provider="openrouter",
        permissions={"read": {"*": "allow"}, "bash": {"*": "allow"}},
        tools={"bash": True, "read": True, "edit": False},
        mcps={},
    )
    base.update(**overrides)
    return AgentConfig(**base)


def test_agent_config_fields_present() -> None:
    config = _config()
    assert config.model == "openrouter/deepseek/deepseek-v4-flash"
    assert config.provider == "openrouter"
    assert config.permissions["read"] == {"*": "allow"}
    assert config.tools["bash"] is True
    assert config.mcps == {}


def test_to_opencode_json_includes_schema() -> None:
    result = to_opencode_json(_config(), {"openrouter": {}}, {})
    assert result["$schema"] == "https://opencode.ai/config.json"


def test_to_opencode_json_includes_provider_defs() -> None:
    provider_defs = {
        "openrouter": {
            "name": "OpenRouter",
            "api": "https://openrouter.ai/api/v1",
        }
    }
    result = to_opencode_json(_config(), provider_defs, {})
    assert result["provider"] == provider_defs


def test_to_opencode_json_includes_permissions() -> None:
    config = _config(
        permissions={"read": {"*": "allow"}, "bash": {"sudo *": "deny", "*": "allow"}}
    )
    result = to_opencode_json(config, {}, {})
    assert result["permission"]["bash"] == {"sudo *": "deny", "*": "allow"}


def test_to_opencode_json_mcp_toggle_enabled() -> None:
    config = _config(mcps={"playwright": True})
    mcp_defs = {
        "playwright": {
            "type": "local",
            "command": ["npx", "@playwright/mcp@latest"],
        }
    }
    result = to_opencode_json(config, {}, mcp_defs)
    assert result["mcp"]["playwright"]["type"] == "local"
    assert result["mcp"]["playwright"]["enabled"] is True


def test_to_opencode_json_mcp_disabled_is_omitted() -> None:
    config = _config(mcps={"playwright": False})
    mcp_defs = {
        "playwright": {
            "type": "local",
            "command": ["npx", "@playwright/mcp@latest"],
        }
    }
    result = to_opencode_json(config, {}, mcp_defs)
    assert "playwright" not in result["mcp"]


def test_to_opencode_json_skills_path_adds_skills_array() -> None:
    import tempfile

    skills_path = tempfile.mkdtemp()
    (Path(skills_path) / "tdd" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (Path(skills_path) / "tdd" / "SKILL.md").write_text("# TDD skill")

    result = to_opencode_json(_config(), {}, {}, skills_path=skills_path)
    assert "skills" in result
    assert result["skills"] == [_SANDBOX_SKILLS_MOUNT]


def test_to_opencode_json_empty_skills_path_omits_skills() -> None:
    result = to_opencode_json(_config(), {}, {}, skills_path="")
    assert "skills" not in result


def test_to_opencode_json_nonexistent_skills_path_omits_skills() -> None:
    result = to_opencode_json(_config(), {}, {}, skills_path="/nonexistent/path")
    assert "skills" not in result
