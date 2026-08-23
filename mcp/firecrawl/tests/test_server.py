"""Test the MCP server starts and registers all three tools."""

import asyncio
import socket

import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_tools_list():
    from firecrawl_mcp.server import create_mcp_server

    mcp = create_mcp_server()
    port = _free_port()

    async def _serve():
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
            response = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
                timeout=5.0,
            )

        assert response.status_code == 200
        body = response.json()
        assert "result" in body, f"Expected result in response: {body}"
        tools = body["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert tool_names == {"fc_search", "fc_scrape", "fc_extract"}, tool_names
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
