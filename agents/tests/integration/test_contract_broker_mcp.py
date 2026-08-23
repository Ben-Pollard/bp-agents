"""Integration test: ContractBroker via FastMCP/streamable-http."""

import asyncio
import json
import socket

import httpx
import pytest
from pydantic import BaseModel

from bp_agents.platform.mcp.contract_broker import (
    ContractBroker,
    create_mcp_server,
)


class _TestContract(BaseModel):
    status: str
    summary: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_submit_contract_via_mcp() -> None:
    broker = ContractBroker()
    broker.register("sdd", "tdd", _TestContract)
    token = broker.create_binding("sdd", "tdd", "run-int-1")

    mcp = create_mcp_server(broker)
    port = _free_port()

    async def _serve() -> None:
        await mcp.run_streamable_http_async(
            host="127.0.0.1",
            port=port,
            json_response=True,
            stateless_http=True,
        )

    server_task = asyncio.create_task(_serve())
    try:
        await asyncio.sleep(0.3)

        async with httpx.AsyncClient() as client:
            url = f"http://127.0.0.1:{port}/mcp"

            call_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "submit_contract",
                    "arguments": {
                        "token": token,
                        "payload": {"status": "DONE", "summary": "ok"},
                    },
                },
            }
            response = await client.post(url, json=call_payload, timeout=5.0)

            assert response.status_code == 200
            body = response.json()
            assert "result" in body, f"Expected result in response: {body}"
            result = body["result"]
            assert result["content"][0]["type"] == "text"
            data = json.loads(result["content"][0]["text"])
            assert data["accepted"] is True
            assert data["contract"]["status"] == "DONE"

    finally:
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass
