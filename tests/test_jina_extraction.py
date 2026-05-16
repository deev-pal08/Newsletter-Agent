"""Tests for Jina Reader extraction in web source."""

from __future__ import annotations

import httpx
import pytest
import respx

from newsletter_agent.sources.web import _parse_markdown_articles, _try_jina

SAMPLE_MARKDOWN = """# Blog Title

## [Critical XSS in WordPress Plugin](https://example.com/xss-wordpress)

Some description of the vulnerability.

## [New Fuzzing Framework Released](https://example.com/fuzzing-framework)

A new tool for fuzzing web applications.

## [SQL Injection 101](https://example.com/sqli-101)

Beginner tutorial on SQL injection.
"""

SAMPLE_MARKDOWN_LINKS = """
Welcome to the security blog.

Here are our latest posts:

[Understanding Buffer Overflows in Modern Systems](https://example.com/buffer-overflows)

[How to Set Up a Security Lab](https://example.com/security-lab)

[Top 10 Bug Bounty Tips for Beginners](https://example.com/bounty-tips)
"""


def test_parse_markdown_heading_links() -> None:
    articles = _parse_markdown_articles(SAMPLE_MARKDOWN, "Test", "https://example.com", None)
    assert len(articles) == 3
    assert articles[0].title == "Critical XSS in WordPress Plugin"
    assert articles[0].url == "https://example.com/xss-wordpress"
    assert articles[0].source_id == "web"


def test_parse_markdown_standalone_links() -> None:
    articles = _parse_markdown_articles(SAMPLE_MARKDOWN_LINKS, "Test", "https://example.com", None)
    assert len(articles) == 3
    assert articles[0].title == "Understanding Buffer Overflows in Modern Systems"


def test_parse_markdown_too_few_articles() -> None:
    articles = _parse_markdown_articles(
        "# One\n[Short](http://a.com)", "Test", "https://x.com", None,
    )
    assert len(articles) == 0


@respx.mock
@pytest.mark.asyncio
async def test_try_jina_success() -> None:
    """Jina Reader should return articles from Markdown response."""
    respx.get("https://r.jina.ai/https://example.com/blog").mock(
        return_value=httpx.Response(200, text=SAMPLE_MARKDOWN),
    )
    async with httpx.AsyncClient() as http:
        articles = await _try_jina(http, "Test Blog", "https://example.com/blog", None)
    assert len(articles) == 3


@respx.mock
@pytest.mark.asyncio
async def test_try_jina_too_short() -> None:
    """Jina Reader should return empty if content is too short."""
    respx.get("https://r.jina.ai/https://example.com/blog").mock(
        return_value=httpx.Response(200, text="Short content"),
    )
    async with httpx.AsyncClient() as http:
        articles = await _try_jina(http, "Test", "https://example.com/blog", None)
    assert len(articles) == 0


@respx.mock
@pytest.mark.asyncio
async def test_try_jina_http_error() -> None:
    """Jina Reader should return empty on HTTP error."""
    respx.get("https://r.jina.ai/https://example.com/blog").mock(
        return_value=httpx.Response(500, text="Error"),
    )
    async with httpx.AsyncClient() as http:
        articles = await _try_jina(http, "Test", "https://example.com/blog", None)
    assert len(articles) == 0
