"""Test extract handler with mocked Firecrawl client."""

import json
from unittest.mock import MagicMock, patch

from firecrawl.v2.utils.error_handler import FirecrawlError


def test_extract_success():
    mock_data = {"title": "Hello", "year": 2024}
    mock_response = MagicMock()
    mock_response.model_dump.return_value = mock_data

    with (
        patch(
            "firecrawl_mcp.extract.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.extract.Firecrawl") as mock_fc,
    ):
        mock_client = MagicMock()
        mock_client.v1.extract.return_value = mock_response
        mock_fc.return_value = mock_client

        from firecrawl_mcp.extract import handle_extract

        result = json.loads(
            handle_extract(url="https://example.com", prompt="Get title and year")
        )

    assert result["title"] == "Hello"
    assert result["year"] == 2024
    mock_client.v1.extract.assert_called_once_with(
        urls=["https://example.com"],
        prompt="Get title and year",
        schema=None,
    )


def test_extract_no_model_dump():
    mock_response = {"raw": "response"}

    with (
        patch(
            "firecrawl_mcp.extract.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.extract.Firecrawl") as mock_fc,
    ):
        mock_client = MagicMock()
        mock_client.v1.extract.return_value = mock_response
        mock_fc.return_value = mock_client

        from firecrawl_mcp.extract import handle_extract

        result = json.loads(
            handle_extract(url="https://example.com", prompt="Get data")
        )

    assert result["raw"] == "response"


def test_extract_missing_api_url():
    from firecrawl_mcp.extract import handle_extract

    result = json.loads(handle_extract(url="https://example.com", prompt="Get data"))
    assert result["success"] is False
    assert "not set" in result["error"]


def test_extract_error():
    with (
        patch(
            "firecrawl_mcp.extract.os.environ", {"FIRECRAWL_API_URL": "http://fc:3002"}
        ),
        patch("firecrawl_mcp.extract.Firecrawl") as mock_fc,
    ):
        mock_client = MagicMock()
        mock_client.v1.extract.side_effect = FirecrawlError("extract failed")
        mock_fc.return_value = mock_client

        from firecrawl_mcp.extract import handle_extract

        result = json.loads(
            handle_extract(url="https://example.com", prompt="Get data")
        )
    assert result["success"] is False
    assert "extract failed" in result["error"]
