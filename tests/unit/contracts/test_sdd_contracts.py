from bp_agents.workflows.sdd import contracts


def test_module_importable() -> None:
    assert hasattr(contracts, "TicketState")
    assert hasattr(contracts, "TddOutput")
