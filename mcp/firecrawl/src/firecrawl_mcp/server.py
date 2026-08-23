import logging
import os
from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from firecrawl_mcp.extract import handle_extract
from firecrawl_mcp.scrape import handle_scrape
from firecrawl_mcp.search import handle_search

logger = logging.getLogger(__name__)

FC_MCP_PORT = int(os.environ.get("FC_MCP_PORT", "8002"))


def create_mcp_server() -> MCPServer:
    mcp = MCPServer("Firecrawl")

    @mcp.tool(
        description=(
            "Search the web using Firecrawl with SearXNG. "
            "Returns a list of results with URLs, titles, and descriptions."
        ),
    )
    def fc_search(
        query: Annotated[str, Field(description="The search query")],
        category: Annotated[
            str,
            Field(
                description=(
                    "SearXNG category prefix. "
                    "Options: '!general', '!images', '!videos', '!news', "
                    "'!map', '!music', '!it', '!science', '!files', '!q&a'. "
                    "Use '!science' for academic research, '!it' for tech topics."
                ),
                default="!general",
            ),
        ] = "!general",
        limit: Annotated[
            int,
            Field(description="Max results to return (1-100).", ge=1, le=100),
        ] = 10,
        location: Annotated[
            str | None,
            Field(
                description="Geo-targeting location (e.g. 'United States').",
                default=None,
            ),
        ] = None,
        ignore_invalid_urls: Annotated[
            bool,
            Field(
                description="Skip invalid URLs instead of failing.",
                default=True,
            ),
        ] = True,
        timeout: Annotated[
            int,
            Field(
                description="Timeout in ms (1000-300000).",
                ge=1000,
                le=300000,
            ),
        ] = 60000,
    ) -> str:
        return handle_search(
            query=query,
            category=category,
            limit=limit,
            location=location,
            ignore_invalid_urls=ignore_invalid_urls,
            timeout=timeout,
        )

    @mcp.tool(
        description=(
            "Scrape a webpage or PDF using Firecrawl. "
            "Returns content in requested formats (markdown, summary, links, images) "
            "with metadata. Supports JavaScript-rendered pages via wait_for."
        ),
    )
    def fc_scrape(
        url: Annotated[str, Field(description="The URL to scrape (webpage or PDF).")],
        formats: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Output formats. "
                    "Options: 'markdown', 'summary', 'links', 'images'. "
                    "Use 'summary' for LLM-generated overview, "
                    "'links' for URLs found on the page, "
                    "'images' for image URLs. "
                    "Combine multiple like ['markdown', 'links']."
                ),
                default=None,
            ),
        ] = None,
        only_main_content: Annotated[
            bool,
            Field(
                description="Extract only main content, excluding nav/footer.",
                default=True,
            ),
        ] = True,
        wait_for: Annotated[
            int | None,
            Field(
                description=(
                    "Wait time in ms for JS-rendered content to load. "
                    "Use for pages that load content dynamically."
                ),
                default=None,
            ),
        ] = None,
        timeout: Annotated[
            int,
            Field(
                description="Timeout in ms (1000-300000).",
                ge=1000,
                le=300000,
            ),
        ] = 300000,
    ) -> str:
        return handle_scrape(
            url=url,
            formats=formats,
            only_main_content=only_main_content,
            wait_for=wait_for,
            timeout=timeout,
        )

    @mcp.tool(
        description=(
            "Extract structured data from webpages using Firecrawl LLM. "
            "Uses an LLM to parse the page and return structured information "
            "based on your prompt. Optionally accepts a JSON schema for strict output format."
        ),
    )
    def fc_extract(
        url: Annotated[str, Field(description="The URL to extract data from.")],
        prompt: Annotated[
            str,
            Field(
                description=(
                    "Description of what data to extract. "
                    "Example: 'Extract the title, author, and publication date.'"
                ),
            ),
        ],
        schema: Annotated[
            dict | None,
            Field(
                description=(
                    "JSON schema defining the structure of data to extract. "
                    "Optional — Firecrawl infers the schema from the prompt if omitted. "
                    "Use for strict output format, e.g.: "
                    '{"type": "object", "properties": {"title": {"type": "string"}}}'
                ),
                default=None,
            ),
        ] = None,
    ) -> str:
        return handle_extract(url=url, prompt=prompt, schema=schema)

    return mcp


async def serve() -> None:
    mcp = create_mcp_server()
    await mcp.run_streamable_http_async(
        host="0.0.0.0",
        port=FC_MCP_PORT,
        json_response=True,
        stateless_http=True,
    )
