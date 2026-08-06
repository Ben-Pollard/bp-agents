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


def test_skill_configs_has_code_review() -> None:
    assert "code_review" in SKILL_CONFIGS
    config = SKILL_CONFIGS["code_review"]
    assert config.tools["edit"] is False


def test_skill_configs_has_revision() -> None:
    assert "revision" in SKILL_CONFIGS
    config = SKILL_CONFIGS["revision"]
    assert config.tools["edit"] is True


def test_skill_configs_has_minimizing_code() -> None:
    assert "minimizing_code" in SKILL_CONFIGS


def test_skill_configs_has_behavioral_verify() -> None:
    assert "behavioral_verify" in SKILL_CONFIGS
    config = SKILL_CONFIGS["behavioral_verify"]
    assert config.mcps.get("playwright") is True


def test_skill_configs_has_deterministic_gate() -> None:
    assert "deterministic_gate" in SKILL_CONFIGS
