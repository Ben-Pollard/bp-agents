"""Test search handler with mocked Firecrawl client."""

import json
from unittest.mock import MagicMock, patch

from firecrawl.v2.utils.error_handler import FirecrawlError


def test_search_success():
    mock_data = {"data": [{"url": "https://example.com", "title": "Example"}]}
    mock_response = MagicMock()
    mock_response.model_dump.return_value = mock_data

    mock_search = MagicMock(return_value=mock_response)

    with (
        patch(
            "firecrawl_mcp.search.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.search.search_module", mock_search),
    ):
        from firecrawl_mcp.search import handle_search

        result = json.loads(handle_search(query="hello world"))

    assert result["data"][0]["url"] == "https://example.com"
    mock_search.assert_called_once()


def test_search_missing_api_url():
    from firecrawl_mcp.search import handle_search

    result = json.loads(handle_search(query="hello"))
    assert result["success"] is False
    assert "not set" in result["error"]


def test_search_category_prepended():
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"data": []}
    mock_search = MagicMock(return_value=mock_response)

    with (
        patch(
            "firecrawl_mcp.search.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.search.search_module", mock_search),
    ):
        from firecrawl_mcp.search import handle_search

        handle_search(query="python", category="!it")

    args, _ = mock_search.call_args
    assert "!it python" in args[1].query


def test_search_error():
    with (
        patch(
            "firecrawl_mcp.search.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch(
            "firecrawl_mcp.search.search_module",
            MagicMock(side_effect=FirecrawlError("API error")),
        ),
    ):
        from firecrawl_mcp.search import handle_search

        result = json.loads(handle_search(query="hello"))
    assert result["success"] is False
    assert "API error" in result["error"]


def test_search_limit_clamped():
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"data": []}
    mock_search = MagicMock(return_value=mock_response)

    with (
        patch(
            "firecrawl_mcp.search.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.search.search_module", mock_search),
    ):
        from firecrawl_mcp.search import handle_search

        handle_search(query="test", limit=999)

    args, _ = mock_search.call_args
    assert args[1].limit == 100
