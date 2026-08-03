from bp_agents.platform.contracts import StageContract


def test_stage_contract_importable() -> None:
    sc: StageContract = {
        "stage": "tdd",
        "direction": "input",
        "timestamp": "2025-01-01T00:00:00Z",
        "payload": {"key": "value"},
    }
    assert sc["stage"] == "tdd"
    assert sc["direction"] == "input"
    assert sc["timestamp"] == "2025-01-01T00:00:00Z"
    assert sc["payload"] == {"key": "value"}
