"""Tests for Exa neural search layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from newsletter_agent.search.models import SearchQuery


def _query(cat: str = "CORE") -> SearchQuery:
    return SearchQuery(id="q01", category=cat, query="test query", rationale="test")


def _mock_exa_result(url: str, title: str = "Test") -> MagicMock:
    r = MagicMock()
    r.url = url
    r.title = title
    r.highlights = ["highlight text"]
    r.text = "full text content"
    r.published_date = "2026-05-01"
    r.score = 0.95
    return r


def test_returns_layer_result():
    with patch("exa_py.Exa") as mock_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.results = [_mock_exa_result("https://example.com/1")]
        mock_client.search_and_contents.return_value = response
        mock_cls.return_value = mock_client

        from newsletter_agent.search.layer_exa import ExaLayer
        layer = ExaLayer(api_key="test-key")
        result = layer.search([_query()])

        assert result.layer_name == "Exa"
        assert result.success is True
        assert len(result.results) == 1


def test_depth_queries_use_keyword_mode():
    with patch("exa_py.Exa") as mock_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.results = [_mock_exa_result("https://example.com/depth")]
        mock_client.search_and_contents.return_value = response
        mock_cls.return_value = mock_client

        from newsletter_agent.search.layer_exa import ExaLayer
        layer = ExaLayer(api_key="test-key")
        layer.search([_query("DEPTH")])

        call_kwargs = mock_client.search_and_contents.call_args[1]
        assert call_kwargs["type"] == "keyword"


def test_single_query_failure_does_not_fail_layer():
    with patch("exa_py.Exa") as mock_cls:
        mock_client = MagicMock()
        response_ok = MagicMock()
        response_ok.results = [_mock_exa_result("https://example.com/ok")]
        mock_client.search_and_contents.side_effect = [
            Exception("API error"),
            response_ok,
        ]
        mock_cls.return_value = mock_client

        from newsletter_agent.search.layer_exa import ExaLayer
        layer = ExaLayer(api_key="test-key")
        result = layer.search([_query(), _query()])

        assert result.success is True
        assert len(result.results) == 1


def test_url_extracted_from_results():
    with patch("exa_py.Exa") as mock_cls:
        mock_client = MagicMock()
        response = MagicMock()
        response.results = [
            _mock_exa_result("https://example.com/a1", "Article 1"),
            _mock_exa_result("https://example.com/a2", "Article 2"),
        ]
        mock_client.search_and_contents.return_value = response
        mock_cls.return_value = mock_client

        from newsletter_agent.search.layer_exa import ExaLayer
        layer = ExaLayer(api_key="test-key")
        result = layer.search([_query()])

        assert len(result.results) == 2
        urls = {r.url for r in result.results}
        assert "https://example.com/a1" in urls
        assert "https://example.com/a2" in urls
