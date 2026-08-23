import asyncio
import logging

from firecrawl_mcp.server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

asyncio.run(serve())
