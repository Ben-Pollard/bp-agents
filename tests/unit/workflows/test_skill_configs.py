from bp_agents.platform.agent_config import AgentConfig
from bp_agents.workflows.sdd.skill_configs import SKILL_CONFIGS


def test_skill_configs_has_tdd() -> None:
    assert "tdd" in SKILL_CONFIGS
    config = SKILL_CONFIGS["tdd"]
    assert isinstance(config, AgentConfig)
    assert config.model == "openrouter/deepseek/deepseek-v4-flash"
    assert config.provider == "openrouter"


def test_skill_configs_tdd_has_tools() -> None:
    config = SKILL_CONFIGS["tdd"]
    assert config.tools["bash"] is True
    assert config.tools["read"] is True
    assert config.tools["edit"] is True
    assert config.tools["task"] is False


def test_skill_configs_tdd_has_permissions() -> None:
    config = SKILL_CONFIGS["tdd"]
    assert config.permissions["read"] == {"*": "allow"}
    assert config.permissions["bash"] == {"*": "allow"}
    assert config.permissions["edit"] == {"*": "allow"}


def test_skill_configs_has_requesting_code_review() -> None:
    assert "requesting-code-review" in SKILL_CONFIGS
    config = SKILL_CONFIGS["requesting-code-review"]
    assert config.tools["edit"] is False


def test_skill_configs_has_receiving_code_review() -> None:
    assert "receiving-code-review" in SKILL_CONFIGS
    config = SKILL_CONFIGS["receiving-code-review"]
    assert config.tools["edit"] is True


def test_skill_configs_has_minimizing_code() -> None:
    assert "minimizing-code" in SKILL_CONFIGS
    config = SKILL_CONFIGS["minimizing-code"]
    assert config.tools["edit"] is False


def test_skill_configs_has_qa() -> None:
    assert "qa" in SKILL_CONFIGS
    config = SKILL_CONFIGS["qa"]
    assert isinstance(config, AgentConfig)
