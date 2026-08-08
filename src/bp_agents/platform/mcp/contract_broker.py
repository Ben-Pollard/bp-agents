import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from mcp.server import MCPServer


@dataclass
class AcceptedContract:
    workflow: str
    stage: str
    run_id: str
    contract: dict


@dataclass
class _Binding:
    workflow: str
    stage: str
    run_id: str
    model: type[BaseModel]
    max_attempts: int
    ttl_seconds: float
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    accepted: bool = False
    event: asyncio.Event = field(default_factory=asyncio.Event)
    invalidated: bool = False
    accepted_contract: dict | None = None


class ContractBroker:
    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], type[BaseModel]] = {}
        self._bindings: dict[str, _Binding] = {}

    def register(self, workflow: str, stage: str, model: type[BaseModel]) -> None:
        key = (workflow, stage)
        if key in self._registry and self._registry[key] is not model:
            msg = f"(workflow={workflow!r}, stage={stage!r}) already registered"
            raise ValueError(msg)
        self._registry[key] = model

    def create_binding(
        self,
        workflow: str,
        stage: str,
        run_id: str,
        max_attempts: int = 3,
        ttl_seconds: float = 3600.0,
    ) -> str:
        key = (workflow, stage)
        if key not in self._registry:
            msg = f"(workflow={workflow!r}, stage={stage!r}) not registered"
            raise ValueError(msg)
        token = secrets.token_urlsafe(32)
        self._bindings[token] = _Binding(
            workflow=workflow,
            stage=stage,
            run_id=run_id,
            model=self._registry[key],
            max_attempts=max_attempts,
            ttl_seconds=ttl_seconds,
        )
        return token

    def _get_binding(self, token: str) -> _Binding | None:
        binding = self._bindings.get(token)
        if binding is None:
            return None
        if binding.invalidated:
            return None
        elapsed = time.time() - binding.created_at
        if elapsed > binding.ttl_seconds:
            return None
        return binding

    @staticmethod
    def _result(
        *,
        accepted: bool,
        terminal: bool,
        contract: dict | None,
        errors: list | None,
        attempts_remaining: int | None,
    ) -> dict:
        return {
            "accepted": accepted,
            "terminal": terminal,
            "contract": contract,
            "errors": errors,
            "attempts_remaining": attempts_remaining,
        }

    def submit(self, token: str, payload: dict) -> dict:
        binding = self._get_binding(token)
        if binding is None:
            return self._result(
                accepted=False,
                terminal=True,
                contract=None,
                errors=[{"field": "_token", "message": "unknown or expired token"}],
                attempts_remaining=None,
            )
        if binding.accepted:
            return self._result(
                accepted=False,
                terminal=True,
                contract=None,
                errors=[{"field": "_binding", "message": "already submitted"}],
                attempts_remaining=None,
            )
        binding.attempts += 1
        remaining = binding.max_attempts - binding.attempts
        try:
            validated = binding.model.model_validate(payload)
        except ValidationError as e:
            if remaining <= 0:
                return self._result(
                    accepted=False,
                    terminal=True,
                    contract=None,
                    errors=[
                        {"field": "_max_attempts", "message": "max attempts exceeded"}
                    ],
                    attempts_remaining=0,
                )
            return self._result(
                accepted=False,
                terminal=False,
                contract=None,
                errors=[
                    {"field": str(err["loc"]), "message": err["msg"]}
                    for err in e.errors()
                ],
                attempts_remaining=remaining,
            )
        binding.accepted = True
        binding.accepted_contract = validated.model_dump()
        binding.event.set()
        return self._result(
            accepted=True,
            terminal=False,
            contract=validated.model_dump(),
            errors=None,
            attempts_remaining=remaining,
        )

    async def await_acceptance(self, token: str) -> AcceptedContract:
        binding = self._bindings.get(token)
        if binding is None:
            raise ValueError(f"unknown token: {token}")
        if binding.invalidated:
            raise ValueError(f"binding invalidated: {token}")
        elapsed = time.time() - binding.created_at
        if elapsed > binding.ttl_seconds:
            raise ValueError(f"binding expired: {token}")
        await binding.event.wait()
        if binding.invalidated:
            raise ValueError(f"binding invalidated: {token}")
        return AcceptedContract(
            workflow=binding.workflow,
            stage=binding.stage,
            run_id=binding.run_id,
            contract=binding.accepted_contract or {},
        )

    def invalidate(self, token: str) -> None:
        binding = self._bindings.pop(token, None)
        if binding is not None:
            binding.invalidated = True
            binding.event.set()


def create_mcp_server(
    broker: ContractBroker, name: str = "ContractBroker"
) -> "MCPServer":
    """Wrap a ContractBroker instance in an MCP server.

    Exposes the submit_contract tool for agents to call.
    """
    from mcp.server import MCPServer

    mcp = MCPServer(name)

    @mcp.tool()
    def submit_contract(
        token: str,
        payload: dict,
    ) -> dict:
        """Submit a stage output contract for validation.

        Args:
            token: The per-dispatch binding token.
            payload: The contract payload to validate against the stage schema.
        Returns:
            A dict with accepted (bool), contract (dict|None), errors (list|None),
            attempts_remaining (int|None), and terminal (bool).
        """
        return broker.submit(token, payload)

    return mcp
