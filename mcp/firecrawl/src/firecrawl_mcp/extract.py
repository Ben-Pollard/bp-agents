import json
import os

from firecrawl import Firecrawl
from firecrawl.v2.utils.error_handler import FirecrawlError


def handle_extract(
    url: str,
    prompt: str,
    schema: dict | None = None,
) -> str:
    api_url = os.environ.get("FIRECRAWL_API_URL")
    if not api_url:
        return json.dumps(
            {
                "success": False,
                "error": "FIRECRAWL_API_URL environment variable not set",
            }
        )

    client = Firecrawl(api_url=api_url)
    try:
        response = client.v1.extract(
            urls=[url],
            prompt=prompt,
            schema=schema,
        )
        if hasattr(response, "model_dump"):
            return json.dumps(response.model_dump(exclude_none=True), default=str)
        return json.dumps(response, default=str)
    except FirecrawlError as e:
        return json.dumps({"success": False, "error": str(e)}, default=str)
