from pydantic import BaseModel

from bp_agents.workflows.sdd import contracts


def test_module_importable() -> None:
    assert hasattr(contracts, "TicketState")
    assert hasattr(contracts, "Ticket")
    assert hasattr(contracts, "TddOutput")


def test_tdd_output_is_base_model() -> None:
    assert issubclass(contracts.TddOutput, BaseModel)


def test_review_output_is_base_model() -> None:
    assert issubclass(contracts.ReviewOutput, BaseModel)


def test_revision_output_is_base_model() -> None:
    assert issubclass(contracts.RevisionOutput, BaseModel)
