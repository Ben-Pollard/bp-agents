import json
import os

from firecrawl import Firecrawl
from firecrawl.v2.methods.search import search as search_module
from firecrawl.v2.types import SearchRequest
from firecrawl.v2.utils.error_handler import FirecrawlError


def handle_search(
    query: str,
    category: str = "!general",
    limit: int = 10,
    location: str | None = None,
    ignore_invalid_urls: bool = True,
    timeout: int = 60000,
) -> str:
    api_url = os.environ.get("FIRECRAWL_API_URL")
    if not api_url:
        return json.dumps(
            {
                "success": False,
                "error": "FIRECRAWL_API_URL environment variable not set",
            }
        )

    limit = min(max(limit, 1), 100)
    full_query = f"{category} {query}" if not query.startswith("!") else query

    request = SearchRequest(
        query=full_query,
        limit=limit,
        location=location if location else None,
        ignore_invalid_urls=ignore_invalid_urls,
        timeout=timeout,
    )

    client = Firecrawl(api_url=api_url)
    try:
        response = search_module(client._v2_client.http_client, request)
        return json.dumps(response.model_dump(exclude_none=True), default=str)
    except FirecrawlError as e:
        return json.dumps({"success": False, "error": str(e)}, default=str)
