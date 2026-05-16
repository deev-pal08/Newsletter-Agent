"""Tests for Tavily-based article scanner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from newsletter_agent.scanner import ArticleScanner, _generate_search_queries


def test_generate_search_queries_default() -> None:
    queries = _generate_search_queries("about me", ["security", "AI", "fuzzing"], num_queries=3)
    assert len(queries) == 3
    assert "security" in queries[0]


def test_generate_search_queries_single_interest() -> None:
    queries = _generate_search_queries("about me", ["security"], num_queries=3)
    assert len(queries) == 3


def test_generate_search_queries_many_interests() -> None:
    queries = _generate_search_queries("", ["a", "b", "c", "d", "e"], num_queries=2)
    assert len(queries) == 2


def test_scanner_no_tavily_key() -> None:
    """Scanner should return empty when TAVILY_API_KEY is not set."""
    config = MagicMock()
    config.interests = ["security"]

    with patch.dict("os.environ", {"TAVILY_API_KEY": ""}, clear=False):
        scanner = ArticleScanner(config, about_me="test")
        results = scanner.search()

    assert results == []


def test_scanner_returns_articles() -> None:
    """Scanner should return Article objects from Tavily results."""
    config = MagicMock()
    config.interests = ["security"]
    config.discovery.tavily_queries_per_scan = 1
    config.discovery.search_depth = "advanced"
    config.discovery.include_domains = []
    config.discovery.exclude_domains = []

    tavily_results = {
        "results": [
            {
                "title": "Critical XSS in WordPress",
                "url": "https://example.com/xss",
                "content": "A critical XSS vulnerability was found.",
            },
            {
                "title": "New Fuzzing Tool Released",
                "url": "https://example.com/fuzzing",
                "content": "A new fuzzing tool for web apps.",
            },
        ],
    }

    with (
        patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}),
        patch("newsletter_agent.scanner.TavilyClient") as mock_tavily_cls,
    ):
        mock_tavily = MagicMock()
        mock_tavily_cls.return_value = mock_tavily
        mock_tavily.search.return_value = tavily_results

        scanner = ArticleScanner(config, about_me="security researcher")
        articles = scanner.search()

    assert len(articles) == 2
    assert articles[0].title == "Critical XSS in WordPress"
    assert articles[0].url == "https://example.com/xss"
    assert articles[0].source_id == "web_search"
    assert articles[0].source_name == "Web Search"
    assert "XSS" in articles[0].raw_summary


def test_scanner_deduplicates_urls() -> None:
    """Scanner should not return duplicate URLs across queries."""
    config = MagicMock()
    config.interests = ["security"]
    config.discovery.tavily_queries_per_scan = 2
    config.discovery.search_depth = "advanced"
    config.discovery.include_domains = []
    config.discovery.exclude_domains = []

    tavily_results = {
        "results": [
            {
                "title": "Same Article",
                "url": "https://example.com/same",
                "content": "Content.",
            },
        ],
    }

    with (
        patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}),
        patch("newsletter_agent.scanner.TavilyClient") as mock_tavily_cls,
    ):
        mock_tavily = MagicMock()
        mock_tavily_cls.return_value = mock_tavily
        mock_tavily.search.return_value = tavily_results

        scanner = ArticleScanner(config, about_me="test")
        articles = scanner.search()

    assert len(articles) == 1


def test_scanner_handles_tavily_error() -> None:
    """Scanner should return empty on Tavily API error."""
    config = MagicMock()
    config.interests = ["security"]
    config.discovery.tavily_queries_per_scan = 1
    config.discovery.search_depth = "advanced"
    config.discovery.include_domains = []
    config.discovery.exclude_domains = []

    with (
        patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}),
        patch("newsletter_agent.scanner.TavilyClient") as mock_tavily_cls,
    ):
        mock_tavily = MagicMock()
        mock_tavily_cls.return_value = mock_tavily
        mock_tavily.search.side_effect = Exception("API error")

        scanner = ArticleScanner(config, about_me="test")
        articles = scanner.search()

    assert articles == []
