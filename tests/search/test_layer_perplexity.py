"""Tests for Perplexity Deep Research layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from newsletter_agent.search.layer_perplexity import (
    PerplexityDeepResearchLayer,
    _extract_urls_from_response,
)
from newsletter_agent.search.models import SearchQuery


def _query() -> SearchQuery:
    return SearchQuery(id="q01", category="CORE", query="test", rationale="test")


def _mock_response(text: str, citations: list[str] | None = None) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.citations = citations or []
    return response


def test_runs_2_prompts():
    with patch("newsletter_agent.search.layer_perplexity.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            "Check https://example.com/article for details."
        )
        mock_cls.return_value = mock_client

        layer = PerplexityDeepResearchLayer(api_key="test-key", prompts_to_run=2)
        layer._client = mock_client
        layer.search([_query()], "AI security", "researcher")

        assert mock_client.chat.completions.create.call_count == 2


def test_extracts_urls_from_citations():
    response = _mock_response(
        "See the report.",
        citations=["https://example.com/cited1", "https://example.com/cited2"],
    )
    results = _extract_urls_from_response(response, "test prompt")
    urls = {r.url for r in results}
    assert "https://example.com/cited1" in urls
    assert "https://example.com/cited2" in urls


def test_extracts_urls_from_text_regex():
    response = _mock_response(
        "Found at https://blog.example.com/post and https://arxiv.org/abs/1234"
    )
    results = _extract_urls_from_response(response, "test prompt")
    urls = {r.url for r in results}
    assert "https://blog.example.com/post" in urls
    assert "https://arxiv.org/abs/1234" in urls


def test_partial_failure_returns_partial_results():
    with patch("newsletter_agent.search.layer_perplexity.openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        ok_response = _mock_response("See https://example.com/ok for details.")
        mock_client.chat.completions.create.side_effect = [
            Exception("timeout"),
            ok_response,
        ]
        mock_cls.return_value = mock_client

        layer = PerplexityDeepResearchLayer(api_key="test-key", prompts_to_run=2)
        layer._client = mock_client
        result = layer.search([_query()], "test topic", "about me")

        assert result.success is True
        assert len(result.results) >= 1
