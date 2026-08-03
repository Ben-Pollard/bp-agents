import pytest

from bp_agents.platform.tracker import Tracker


def test_tracker_is_abstract() -> None:
    with pytest.raises(TypeError):
        Tracker()  # type: ignore[abstract]


def test_tracker_has_abstract_methods() -> None:
    methods = ["list_ready", "update_state"]
    for m in methods:
        assert hasattr(Tracker, m)
        assert getattr(Tracker, m).__isabstractmethod__
