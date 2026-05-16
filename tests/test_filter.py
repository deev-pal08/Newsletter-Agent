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
    """Filter should remove articles marked as irrelevant."""
    articles = _make_articles(4)
    verdicts = [True, False, True, False]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(verdicts)

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


def test_filter_keeps_all_on_all_true() -> None:
    """Filter should keep all articles when all are relevant."""
    articles = _make_articles(3)
    verdicts = [True, True, True]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(verdicts)

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


def test_filter_mismatched_verdicts_adjusts() -> None:
    """If verdict count is off by 1-2, pad with True and keep going."""
    articles = _make_articles(4)
    verdicts = [True, False]  # 2 short — gets padded with [True, True]

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(verdicts)

    with (
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}),
        patch("newsletter_agent.ranking.filter.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        result = filter_articles(articles, interests=["security"])

    # [True, False, True(pad), True(pad)] → keeps 3 of 4
    assert len(result) == 3


def test_filter_empty_articles() -> None:
    """Empty input should return empty output."""
    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"}):
        result = filter_articles([], interests=["security"])
    assert result == []
