"""Test scrape handler with mocked Firecrawl client."""

import json
from unittest.mock import MagicMock, patch

from firecrawl.v2.utils.error_handler import FirecrawlError


def test_scrape_success():
    mock_data = {"content": "# Hello", "metadata": {"title": "Test"}}
    mock_response = MagicMock()
    mock_response.model_dump.return_value = mock_data

    mock_scrape = MagicMock(return_value=mock_response)

    with (
        patch(
            "firecrawl_mcp.scrape.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.scrape.scrape_module", mock_scrape),
    ):
        from firecrawl_mcp.scrape import handle_scrape

        result = json.loads(handle_scrape(url="https://example.com"))

    assert result["metadata"]["title"] == "Test"
    mock_scrape.assert_called_once()


def test_scrape_missing_api_url():
    from firecrawl_mcp.scrape import handle_scrape

    result = json.loads(handle_scrape(url="https://example.com"))
    assert result["success"] is False
    assert "not set" in result["error"]


def test_scrape_custom_formats():
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"content": "data"}
    mock_scrape = MagicMock(return_value=mock_response)

    with (
        patch(
            "firecrawl_mcp.scrape.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.scrape.scrape_module", mock_scrape),
    ):
        from firecrawl_mcp.scrape import handle_scrape

        handle_scrape(url="https://example.com", formats=["markdown", "links"])

    args, _ = mock_scrape.call_args
    assert args[2].formats == ["markdown", "links"]


def test_scrape_error():
    with (
        patch(
            "firecrawl_mcp.scrape.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch(
            "firecrawl_mcp.scrape.scrape_module",
            MagicMock(side_effect=FirecrawlError("scrape failed")),
        ),
    ):
        from firecrawl_mcp.scrape import handle_scrape

        result = json.loads(handle_scrape(url="https://example.com"))
    assert result["success"] is False
    assert "scrape failed" in result["error"]
