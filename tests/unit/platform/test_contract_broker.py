"""Tests for ContractBroker — contract validation lifecycle."""

import asyncio

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


class TestAwaitAcceptance:
    @pytest.mark.asyncio
    async def test_blocks_until_acceptance(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-5")

        async def submit_later() -> None:
            await asyncio.sleep(0.05)
            registered_broker.submit(
                token,
                {
                    "status": "DONE",
                    "summary": "ok",
                    "results": {"passed": 1},
                },
            )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(submit_later())
            accepted = await registered_broker.await_acceptance(token)

        assert accepted.workflow == "sdd"
        assert accepted.stage == "tdd"
        assert accepted.run_id == "run-5"
        assert accepted.contract["status"] == "DONE"

    @pytest.mark.asyncio
    async def test_raises_for_unknown_token(self, broker: ContractBroker) -> None:
        with pytest.raises(ValueError, match="unknown token"):
            await broker.await_acceptance("no-such-token")


class TestInvalidate:
    def test_idempotent(self, registered_broker: ContractBroker) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-6")
        registered_broker.invalidate(token)
        registered_broker.invalidate(token)

    @pytest.mark.asyncio
    async def test_await_acceptance_raises_after_invalidation(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding("sdd", "tdd", "run-7")
        registered_broker.invalidate(token)
        with pytest.raises(ValueError, match="invalidated"):
            await registered_broker.await_acceptance(token)


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

    @pytest.mark.asyncio
    async def test_await_expired_token_raises(
        self, registered_broker: ContractBroker
    ) -> None:
        token = registered_broker.create_binding(
            "sdd", "tdd", "run-9", ttl_seconds=-1.0
        )
        with pytest.raises(ValueError, match="expired"):
            await registered_broker.await_acceptance(token)
