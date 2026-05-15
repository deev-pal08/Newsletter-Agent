"""Generic web source — deterministic extraction first, AI fallback second.

Extraction strategy per page (stops at first success):
1. JSON API — if the response is JSON, extract articles from common structures
2. RSS autodiscovery — if the page links to a feed, fetch and parse it
3. HTML structure — look for <article> tags, common listing patterns
4. AI fallback — send page text to Claude Haiku for extraction
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from time import mktime
from urllib.parse import urljoin

import anthropic
import feedparser
import httpx
from bs4 import BeautifulSoup, Tag

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 30000

AI_EXTRACTION_PROMPT = """\
Extract all blog posts, articles, reports, or write-ups from this webpage.

Return a JSON array of objects with these fields:
- "title": article title (string)
- "url": full URL (string) — resolve relative links using the base URL
- "date": publication date (ISO 8601 YYYY-MM-DD) or null
- "summary": one-sentence description from the page, or empty string

Only extract content items (posts, articles, reports, write-ups, disclosures).
Do NOT extract navigation links, category links, author pages, or site chrome.
Return ONLY the JSON array — no markdown fences, no explanation.
If no articles found, return: []

Base URL: {base_url}

Page content:
{content}"""


class WebSource(BaseSource):
    def __init__(self, pages: dict[str, str], api_key: str | None = None):
        self._pages = pages
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def name(self) -> str:
        return "Web Pages"

    @property
    def source_id(self) -> str:
        return "web"

    def is_available(self) -> bool:
        return bool(self._pages)

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        articles: list[Article] = []

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsletterAgent/1.0)"},
        ) as http:
            for page_name, page_url in self._pages.items():
                try:
                    page_articles = await self._extract_from_page(
                        http, page_name, page_url, since,
                    )
                    articles.extend(page_articles)
                except Exception:
                    logger.exception("WebSource failed for '%s'", page_name)
                    continue

        return articles

    async def _extract_from_page(
        self,
        http: httpx.AsyncClient,
        page_name: str,
        page_url: str,
        since: datetime | None,
    ) -> list[Article]:
        resp = await http.get(page_url)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        # Strategy 1: JSON API response
        if "json" in content_type or resp.text.lstrip().startswith(("{", "[")):
            articles = _try_json(resp.text, page_name, page_url, since)
            if articles:
                logger.info("  %s: %d articles via JSON API", page_name, len(articles))
                return articles

        # Strategy 2: RSS/Atom autodiscovery
        feed_url = _find_feed_link(resp.text, page_url)
        if feed_url:
            articles = await _try_feed(http, feed_url, page_name, since)
            if articles:
                logger.info("  %s: %d articles via RSS autodiscovery", page_name, len(articles))
                return articles

        # Strategy 3: HTML structural extraction
        articles = _try_html(resp.text, page_name, page_url, since)
        if articles:
            logger.info("  %s: %d articles via HTML structure", page_name, len(articles))
            return articles

        # Strategy 4: AI fallback
        if not self._api_key:
            logger.warning("  %s: no articles found deterministically, and no API key for AI fallback", page_name)
            return []

        articles = _try_ai(resp.text, page_name, page_url, since, self._api_key)
        logger.info("  %s: %d articles via AI extraction", page_name, len(articles))
        return articles


# ---------------------------------------------------------------------------
# Strategy 1: JSON API
# ---------------------------------------------------------------------------

def _try_json(
    text: str,
    page_name: str,
    page_url: str,
    since: datetime | None,
) -> list[Article]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    items = _find_json_items(data)
    if not items:
        return []

    articles = []
    for item in items:
        title = _get_json_field(item, ["title", "name", "headline"])
        url = _get_json_field(item, ["url", "link", "href"])
        if not title:
            continue

        if url:
            url = urljoin(page_url, url)
        else:
            item_id = _get_json_field(item, ["id", "report_id", "slug"])
            if item_id:
                url = f"{page_url.rstrip('/')}#{item_id}"
            else:
                url = page_url

        date_str = _get_json_field(
            item, ["date", "published_at", "created_at", "disclosed_at",
                   "published", "pubDate", "created", "timestamp"],
        )
        published = _parse_date(date_str)
        if since and published and published < since:
            continue

        summary = _get_json_field(item, ["summary", "description", "excerpt", "abstract"]) or ""

        articles.append(Article(
            title=title,
            url=url,
            source_id="web",
            source_name=page_name,
            published_at=published,
            raw_summary=summary[:500],
        ))
    return articles


def _find_json_items(data: object) -> list[dict[str, object]]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data  # type: ignore[return-value]
    if isinstance(data, dict):
        for key in ("reports", "articles", "posts", "items", "entries",
                     "results", "data", "records", "feed", "stories"):
            val = data.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val  # type: ignore[return-value]
        for val in data.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val  # type: ignore[return-value]
    return []


def _get_json_field(item: dict[str, object], keys: list[str]) -> str | None:
    for key in keys:
        val = item.get(key)
        if val is not None:
            return str(val).strip()
    return None


# ---------------------------------------------------------------------------
# Strategy 2: RSS/Atom autodiscovery
# ---------------------------------------------------------------------------

def _find_feed_link(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("link", type=True):
        link_type = link.get("type", "")
        if "rss" in link_type or "atom" in link_type:
            href = link.get("href", "")
            if href:
                return urljoin(base_url, href)
    return None


async def _try_feed(
    http: httpx.AsyncClient,
    feed_url: str,
    page_name: str,
    since: datetime | None,
) -> list[Article]:
    try:
        resp = await http.get(feed_url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    parsed = feedparser.parse(resp.text)
    articles = []
    for entry in parsed.entries:
        published = _parse_feed_date(entry)
        if since and published and published < since:
            continue
        title = entry.get("title", "")
        url = entry.get("link", "")
        if not title or not url:
            continue
        summary = entry.get("summary", "")
        if len(summary) > 500:
            summary = summary[:500] + "..."
        articles.append(Article(
            title=title,
            url=url,
            source_id="web",
            source_name=page_name,
            published_at=published,
            raw_summary=summary,
        ))
    return articles


def _parse_feed_date(entry: object) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:  # type: ignore[union-attr]
        return datetime.fromtimestamp(mktime(entry.published_parsed), tz=UTC)  # type: ignore[union-attr]
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:  # type: ignore[union-attr]
        return datetime.fromtimestamp(mktime(entry.updated_parsed), tz=UTC)  # type: ignore[union-attr]
    return None


# ---------------------------------------------------------------------------
# Strategy 3: HTML structural extraction
# ---------------------------------------------------------------------------

def _try_html(
    html: str,
    page_name: str,
    page_url: str,
    since: datetime | None,
) -> list[Article]:
    soup = BeautifulSoup(html, "html.parser")

    # Try <article> tags first
    articles = _extract_from_article_tags(soup, page_name, page_url)
    if articles:
        return articles

    # Try common listing patterns: divs/lis with heading + link combos
    articles = _extract_from_listing_patterns(soup, page_name, page_url)
    return articles


def _extract_from_article_tags(
    soup: BeautifulSoup,
    page_name: str,
    page_url: str,
) -> list[Article]:
    article_tags = soup.find_all("article")
    if len(article_tags) < 2:
        return []

    articles = []
    for tag in article_tags:
        link = tag.find("a", href=True)
        if not link or not isinstance(link, Tag):
            continue

        heading = tag.find(["h1", "h2", "h3", "h4"])
        title = heading.get_text(strip=True) if heading else link.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        url = urljoin(page_url, link["href"])  # type: ignore[arg-type]

        time_tag = tag.find("time")
        published = None
        if time_tag and isinstance(time_tag, Tag):
            published = _parse_date(time_tag.get("datetime") or time_tag.get_text(strip=True))  # type: ignore[arg-type]

        summary = ""
        for p in tag.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 30 and text != title:
                summary = text[:500]
                break

        articles.append(Article(
            title=title,
            url=url,
            source_id="web",
            source_name=page_name,
            published_at=published,
            raw_summary=summary,
        ))
    return articles


def _extract_from_listing_patterns(
    soup: BeautifulSoup,
    page_name: str,
    page_url: str,
) -> list[Article]:
    articles = []
    seen_urls: set[str] = set()

    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        if not link or not isinstance(link, Tag):
            continue

        title = link.get_text(strip=True)
        href = str(link.get("href", ""))
        if not title or len(title) < 5 or not href:
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue

        url = urljoin(page_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        articles.append(Article(
            title=title,
            url=url,
            source_id="web",
            source_name=page_name,
            published_at=None,
            raw_summary="",
        ))

    # Only return if we found a meaningful number of items
    if len(articles) >= 3:
        return articles
    return []


# ---------------------------------------------------------------------------
# Strategy 4: AI extraction (Claude Haiku)
# ---------------------------------------------------------------------------

def _try_ai(
    html: str,
    page_name: str,
    page_url: str,
    since: datetime | None,
    api_key: str,
) -> list[Article]:
    content = _html_to_text(html, page_url)
    if not content.strip():
        return []

    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH]

    prompt = AI_EXTRACTION_PROMPT.format(base_url=page_url, content=content)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text  # type: ignore[union-attr]
    extracted = _parse_json_response(text)

    articles = []
    for item in extracted:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        if not title or not url:
            continue

        url = urljoin(page_url, url)

        published = _parse_date(item.get("date"))
        if since and published and published < since:
            continue

        articles.append(Article(
            title=title,
            url=url,
            source_id="web",
            source_name=page_name,
            published_at=published,
            raw_summary=item.get("summary", ""),
        ))
    return articles


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _html_to_text(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(base_url, href)
        a.string = f"{a.get_text()} [{full_url}]"

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _parse_json_response(text: str) -> list[dict[str, str]]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.warning("Failed to parse AI extraction response")

    return []


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass
    try:
        from dateutil.parser import parse as dateutil_parse
        dt = dateutil_parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None
