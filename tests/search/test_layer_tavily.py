"""Tests for Tavily search layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from newsletter_agent.search.layer_tavily import TavilyLayer
from newsletter_agent.search.models import SearchQuery


def _query(cat: str = "CORE") -> SearchQuery:
    return SearchQuery(id="q01", category=cat, query="test query", rationale="test")


def test_returns_layer_result():
    with patch("newsletter_agent.search.layer_tavily.TavilyClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"url": "https://example.com/1", "title": "Test", "content": "desc", "score": 0.9},
            ]
        }
        mock_cls.return_value = mock_client

        layer = TavilyLayer(api_key="test-key")
        layer._client = mock_client
        result = layer.search([_query()])

        assert result.layer_name == "Tavily"
        assert result.success is True
        assert len(result.results) == 1
        assert result.results[0].source_layer == "tavily"


def test_single_query_failure_does_not_fail_layer():
    with patch("newsletter_agent.search.layer_tavily.TavilyClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            Exception("rate limit"),
            {"results": [{"url": "https://example.com/2", "title": "OK", "content": "ok"}]},
        ]
        mock_cls.return_value = mock_client

        layer = TavilyLayer(api_key="test-key")
        layer._client = mock_client
        result = layer.search([_query(), _query()])

        assert result.success is True
        assert len(result.results) == 1


def test_url_extracted_from_results():
    with patch("newsletter_agent.search.layer_tavily.TavilyClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"url": "https://example.com/article", "title": "Article", "content": "content"},
                {"url": "", "title": "Empty URL", "content": "should be skipped"},
            ]
        }
        mock_cls.return_value = mock_client

        layer = TavilyLayer(api_key="test-key")
        layer._client = mock_client
        result = layer.search([_query()])

        assert len(result.results) == 1
        assert result.results[0].url == "https://example.com/article"
