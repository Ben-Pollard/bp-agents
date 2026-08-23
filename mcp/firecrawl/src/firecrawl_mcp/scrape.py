import json
import os

from firecrawl import Firecrawl
from firecrawl.v2.methods.scrape import scrape as scrape_module
from firecrawl.v2.types import ScrapeOptions
from firecrawl.v2.utils.error_handler import FirecrawlError


def handle_scrape(
    url: str,
    formats: list[str] | None = None,
    only_main_content: bool = True,
    wait_for: int | None = None,
    timeout: int = 300000,
) -> str:
    api_url = os.environ.get("FIRECRAWL_API_URL")
    if not api_url:
        return json.dumps(
            {
                "success": False,
                "error": "FIRECRAWL_API_URL environment variable not set",
            }
        )

    options = ScrapeOptions(
        formats=formats or ["markdown"],
        only_main_content=only_main_content,
        wait_for=wait_for,
        timeout=timeout,
    )

    client = Firecrawl(api_url=api_url)
    try:
        response = scrape_module(client._v2_client.http_client, url, options)
        return json.dumps(response.model_dump(exclude_none=True), default=str)
    except FirecrawlError as e:
        return json.dumps({"success": False, "error": str(e)}, default=str)
