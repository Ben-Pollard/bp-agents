"""Tests for ContractBroker — contract validation lifecycle."""

import pytest
from pydantic import BaseModel

from bp_agents.platform.mcp.contract_broker import ContractBroker


class FakeContract(BaseModel):
    status: str
    summary: str
    results: dict


class FakeAltContract(BaseModel):
    value: int


@pytest.fixture
def broker() -> ContractBroker:
    return ContractBroker()


@pytest.fixture
def registered_broker(broker: ContractBroker) -> ContractBroker:
    broker.register("sdd", "tdd", FakeContract)
    return broker


class TestRegister:
    def test_register_accepts_model(self, broker: ContractBroker) -> None:
        broker.register("sdd", "tdd", FakeContract)
        assert ("sdd", "tdd") in broker._registry

    def test_register_idempotent_same_model(self, broker: ContractBroker) -> None:
        broker.register("sdd", "tdd", FakeContract)
        broker.register("sdd", "tdd", FakeContract)

    def test_register_raises_on_duplicate_different_model(
        self, broker: ContractBroker
    ) -> None:
        broker.register("sdd", "tdd", FakeContract)
        with pytest.raises(ValueError, match="already registered"):
            broker.register("sdd", "tdd", FakeAltContract)


class TestCreateBinding:
    def test_returns_opaque_token(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-1")
        assert isinstance(token, str)
        assert len(token) > 16

    def test_raises_for_unregistered_workflow_stage(
        self, broker: ContractBroker
    ) -> None:
        with pytest.raises(ValueError, match="not registered"):
            broker.create_binding("unknown", "stage", "run-1")

    def test_different_tokens_for_different_bindings(
        self, registered_broker: ContractBroker
    ) -> None:
        t1 = registered_broker.create_binding("sdd", "tdd", "run-1")
        t2 = registered_broker.create_binding("sdd", "tdd", "run-2")
        assert t1 != t2


class TestSubmit:
    def test_accepts_valid_payload(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-1")
        result = registered_broker.submit(
            token,
            {
                "status": "DONE",
                "summary": "ok",
                "results": {"passed": 1},
            },
        )
        assert result["accepted"] is True
        assert result["contract"]["status"] == "DONE"
        assert result["terminal"] is False

    def test_rejects_invalid_payload(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-2")
        result = registered_broker.submit(token, {"status": "DONE"})
        assert result["accepted"] is False
        assert result["errors"] is not None
        assert len(result["errors"]) > 0
        assert result["terminal"] is False
        assert result["attempts_remaining"] is not None

    def test_terminal_after_max_attempts(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-3", max_attempts=2)
        r1 = registered_broker.submit(token, {"status": "DONE"})
        assert r1["accepted"] is False
        assert r1["attempts_remaining"] == 1
        r2 = registered_broker.submit(token, {"status": "DONE"})
        assert r2["accepted"] is False
        assert r2["terminal"] is True

    def test_terminal_already_submitted(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-4")
        valid = registered_broker.submit(
            token,
            {
                "status": "DONE",
                "summary": "ok",
                "results": {"passed": 1},
            },
        )
        assert valid["accepted"] is True
        second = registered_broker.submit(
            token, {"status": "DONE", "summary": "again", "results": {}}
        )
        assert second["accepted"] is False
        assert second["terminal"] is True

    def test_terminal_for_unknown_token(
        self, registered_broker: ContractBroker
    ) -> None:
        result = registered_broker.submit("unknown-token", {})
        assert result["accepted"] is False
        assert result["terminal"] is True


class TestExpiry:
    def test_expired_token_returns_terminal(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding(
            "sdd", "tdd", "run-8", ttl_seconds=-1.0
        )
        result = registered_broker.submit(token, {})
        assert result["accepted"] is False
        assert result["terminal"] is True


class TestSubmissionStatus:
    def test_returns_accepted(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-s1")
        registered_broker.submit(
            token,
            {
                "status": "DONE",
                "summary": "ok",
                "results": {"passed": 1},
            },
        )
        assert registered_broker.submission_status(token) == "accepted"

    def test_returns_pending_when_no_submission(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-s2")
        assert registered_broker.submission_status(token) == "pending"

    def test_returns_exhausted(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-s3", max_attempts=2)
        registered_broker.submit(token, {"status": "DONE"})
        registered_broker.submit(token, {"status": "DONE"})
        assert registered_broker.submission_status(token) == "exhausted"

    def test_returns_none_for_unknown_token(
        self, registered_broker: ContractBroker
    ) -> None:
        assert registered_broker.submission_status("no-such-token") is None

    def test_returns_none_for_expired_token(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding(
            "sdd", "tdd", "run-s5", ttl_seconds=-1.0
        )
        assert registered_broker.submission_status(token) is None
