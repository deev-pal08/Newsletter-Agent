"""Tests for DeepSeek relevance filter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from newsletter_agent.models import Article
from newsletter_agent.ranking.filter import filter_articles


def _make_articles(n: int) -> list[Article]:
    return [
        Article(
            title=f"Article {i}",
            url=f"https://example.com/article-{i}",
            source_id="test",
            source_name="Test Source",
            raw_summary=f"Summary {i}",
        )
        for i in range(n)
    ]


def test_filter_no_api_key() -> None:
    """Without DEEPSEEK_API_KEY, filter should pass all articles through."""
    articles = _make_articles(5)
    with patch.dict("os.environ", {}, clear=True):
        result = filter_articles(articles, interests=["security"])
    assert len(result) == 5


def test_filter_removes_irrelevant() -> None:
    """Filter should remove articles not in the returned indices."""
    articles = _make_articles(4)
    keep_indices = [0, 2]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(keep_indices)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        result = filter_articles(articles, interests=["security"], about_me="Test user")

    assert len(result) == 2
    assert result[0].title == "Article 0"
    assert result[1].title == "Article 2"


def test_filter_keeps_all_when_all_indices_returned() -> None:
    """Filter should keep all articles when all indices are returned."""
    articles = _make_articles(3)
    keep_indices = [0, 1, 2]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(keep_indices)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        result = filter_articles(articles, interests=["security"])

    assert len(result) == 3


def test_filter_fail_open_on_error() -> None:
    """On API error with fail_open=True, should return all articles."""
    articles = _make_articles(3)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")

        result = filter_articles(articles, interests=["security"], fail_open=True)

    assert len(result) == 3


def test_filter_fail_closed_on_error() -> None:
    """On API error with fail_open=False, should raise."""
    articles = _make_articles(3)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError):
            filter_articles(articles, interests=["security"], fail_open=False)


def test_filter_ignores_out_of_range_indices() -> None:
    """Out-of-range indices should be silently ignored."""
    articles = _make_articles(4)
    keep_indices = [0, 2, 99, -1]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(keep_indices)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        result = filter_articles(articles, interests=["security"])

    assert len(result) == 2
    assert result[0].title == "Article 0"
    assert result[1].title == "Article 2"


def test_filter_topic_mode() -> None:
    """Topic mode should pass the topic to the filter."""
    articles = _make_articles(3)
    keep_indices = [1]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(keep_indices)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        result = filter_articles(
            articles, interests=["security"], topic="Prompt Injection",
        )

    assert len(result) == 1
    assert result[0].title == "Article 1"
    prompt_used = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
    assert "Prompt Injection" in prompt_used


def test_filter_empty_articles() -> None:
    """Empty input should return empty output."""
    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
        result = filter_articles([], interests=["security"])
    assert result == []
