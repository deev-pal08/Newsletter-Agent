"""Tests for LLM-based search result classifier."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import respx

from newsletter_agent.search.classifier import classify_search_results
from newsletter_agent.search.models import SearchResult


def test_classify_search_results_success():
    """Test successful classification via DeepSeek API."""
    results = [
        SearchResult(
            url="https://genai.owasp.org/llm-top-10",
            title="OWASP LLM Top 10",
            description="Top 10 risks",
            source_layer="exa",
            source_query="test",
            query_category="CORE",
        ),
        SearchResult(
            url="https://arxiv.org/html/2603.29418v1",
            title="Adversarial Prompt Injection Attack",
            description="Research paper",
            source_layer="exa",
            source_query="test",
            query_category="DEPTH",
        ),
    ]

    mock_response = {
        "choices": [{
            "message": {
                "content": """
                {
                  "classifications": [
                    {"url": "https://genai.owasp.org/llm-top-10", "type": "index"},
                    {"url": "https://arxiv.org/html/2603.29418v1", "type": "article"}
                  ]
                }
                """
            }
        }]
    }

    with respx.mock:
        respx.post("https://api.deepseek.com/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        classifications = classify_search_results(results, api_key="test-key")

    assert classifications["https://genai.owasp.org/llm-top-10"] == "index"
    assert classifications["https://arxiv.org/html/2603.29418v1"] == "article"


def test_classify_search_results_no_api_key():
    """Test fallback to 'article' when no API key provided."""
    results = [
        SearchResult(
            url="https://example.com/page",
            title="Test",
            description="",
            source_layer="exa",
            source_query="test",
            query_category="CORE",
        ),
    ]

    with patch.dict("os.environ", {}, clear=True):
        classifications = classify_search_results(results, api_key=None)

    assert classifications["https://example.com/page"] == "article"


def test_classify_search_results_api_error():
    """Test fallback to 'article' when API call fails."""
    results = [
        SearchResult(
            url="https://example.com/page",
            title="Test",
            description="",
            source_layer="exa",
            source_query="test",
            query_category="CORE",
        ),
    ]

    with respx.mock:
        respx.post("https://api.deepseek.com/chat/completions").mock(
            return_value=httpx.Response(500, text="Server error")
        )

        classifications = classify_search_results(results, api_key="test-key")

    assert classifications["https://example.com/page"] == "article"


def test_classify_search_results_empty_list():
    """Test that empty list returns empty dict."""
    classifications = classify_search_results([], api_key="test-key")
    assert classifications == {}


def test_classify_search_results_malformed_json():
    """Test fallback when API returns malformed JSON."""
    results = [
        SearchResult(
            url="https://example.com/page",
            title="Test",
            description="",
            source_layer="exa",
            source_query="test",
            query_category="CORE",
        ),
    ]

    mock_response = {
        "choices": [{
            "message": {
                "content": "Not valid JSON"
            }
        }]
    }

    with respx.mock:
        respx.post("https://api.deepseek.com/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        classifications = classify_search_results(results, api_key="test-key")

    assert classifications["https://example.com/page"] == "article"
