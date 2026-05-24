"""Generic web source — deterministic extraction first, Jina/Firecrawl middle, AI fallback last.

Extraction strategy per page (stops at first success):
1. JSON API — if the response is JSON, extract articles from common structures
2. RSS autodiscovery — if the page links to a feed, fetch and parse it
3. Jina Reader — prepend https://r.jina.ai/ to get clean Markdown (free)
4. Firecrawl — JS-heavy fallback via firecrawl API (optional, needs key)
5. HTML structure — extract articles from semantic HTML tags and patterns
6. AI fallback — send page text to Claude Haiku for extraction
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from time import mktime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import anthropic
import feedparser
import httpx
from bs4 import BeautifulSoup, Tag

from newsletter_agent.models import Article

if TYPE_CHECKING:
    from newsletter_agent.report import RunReport
from newsletter_agent.sources.base import BaseSource
from newsletter_agent.validation import is_junk_article_url

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
    def __init__(
        self,
        pages: dict[str, str],
        api_key: str | None = None,
        jina_enabled: bool = True,
        firecrawl_enabled: bool = False,
        haiku_fallback_enabled: bool = True,
        max_pages: int = 3,
        model: str = "claude-haiku-4-5",
    ):
        self._pages = pages
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.jina_enabled = jina_enabled
        self.firecrawl_enabled = firecrawl_enabled
        self.haiku_fallback_enabled = haiku_fallback_enabled
        self.max_pages = max_pages
        self.model = model

    @property
    def name(self) -> str:
        return "Web Pages"

    @property
    def source_id(self) -> str:
        return "web"

    def is_available(self) -> bool:
        return bool(self._pages)

    async def fetch(
        self,
        report: RunReport | None = None,
    ) -> list[Article]:
        articles: list[Article] = []

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsletterAgent/1.0)"},
        ) as http:
            for page_name, page_url in self._pages.items():
                try:
                    page_articles = await self._fetch_with_pagination(
                        http, page_name, page_url, report,
                    )
                    articles.extend(page_articles)
                except Exception as e:
                    logger.warning("WebSource failed for '%s': %s", page_name, e)
                    if report is not None:
                        report.add_web_failed(page_name, str(e))
                    continue

        return articles

    async def _fetch_with_pagination(
        self,
        http: httpx.AsyncClient,
        page_name: str,
        page_url: str,
        report: RunReport | None,
    ) -> list[Article]:
        all_articles: list[Article] = []
        current_url = page_url
        seen_urls: set[str] = set()
        pages_fetched = 0

        while current_url and pages_fetched < self.max_pages:
            if current_url in seen_urls:
                break
            seen_urls.add(current_url)

            page_articles, strategy, raw_html = await self._extract_from_page(
                http, page_name, current_url,
            )
            all_articles.extend(page_articles)
            pages_fetched += 1

            if pages_fetched == 1 and report is not None:
                if page_articles:
                    report.add_web_ok(page_name, strategy)
                else:
                    report.add_web_failed(page_name, "no articles found")

            if pages_fetched < self.max_pages and raw_html:
                next_url = _find_next_page_url(raw_html, current_url)
                if next_url and next_url != current_url:
                    logger.debug(
                        "  %s: following pagination → %s (page %d)",
                        page_name, next_url, pages_fetched + 1,
                    )
                    current_url = next_url
                else:
                    break
            else:
                break

        if pages_fetched > 1:
            logger.info(
                "  %s: %d articles across %d pages",
                page_name, len(all_articles), pages_fetched,
            )

        return all_articles

    async def _extract_from_page(
        self,
        http: httpx.AsyncClient,
        page_name: str,
        page_url: str,
    ) -> tuple[list[Article], str, str]:
        """Extract articles from a page. Returns (articles, strategy_name, raw_html)."""
        resp = await http.get(page_url)
        resp.raise_for_status()
        raw_html = resp.text

        content_type = resp.headers.get("content-type", "")

        # Strategy 1: JSON API response
        if "json" in content_type or resp.text.lstrip().startswith(("{", "[")):
            articles = _try_json(resp.text, page_name, page_url)
            if articles:
                logger.info("  %s: %d articles via JSON API", page_name, len(articles))
                return articles, "JSON API", raw_html

        # Strategy 2: RSS/Atom autodiscovery
        feed_url = _find_feed_link(resp.text, page_url)
        if feed_url:
            articles = await _try_feed(http, feed_url, page_name)
            if articles:
                logger.info("  %s: %d articles via RSS autodiscovery", page_name, len(articles))
                return articles, "RSS autodiscovery", raw_html

        # Strategy 3: Jina Reader (free Markdown extraction)
        if self.jina_enabled:
            articles = await _try_jina(http, page_name, page_url)
            if articles:
                logger.info("  %s: %d articles via Jina Reader", page_name, len(articles))
                return articles, "Jina Reader", raw_html

        # Strategy 4: Firecrawl (JS-heavy fallback)
        if self.firecrawl_enabled and os.environ.get("FIRECRAWL_API_KEY"):
            articles = _try_firecrawl(page_name, page_url)
            if articles:
                logger.info("  %s: %d articles via Firecrawl", page_name, len(articles))
                return articles, "Firecrawl", raw_html
        elif self.firecrawl_enabled:
            logger.debug(
                "  %s: FIRECRAWL_API_KEY not set — skipping Firecrawl",
                page_name,
            )

        # Strategy 5: HTML structural extraction
        articles = _try_html(resp.text, page_name, page_url)
        if articles:
            logger.info("  %s: %d articles via HTML structure", page_name, len(articles))
            return articles, "HTML", raw_html

        # Strategy 6: AI fallback (Claude Haiku)
        if not self.haiku_fallback_enabled:
            logger.warning("  %s: no articles found, AI fallback disabled", page_name)
            return [], "none", raw_html

        if not self._api_key:
            logger.warning(
                "  %s: no articles found, no API key for AI fallback",
                page_name,
            )
            return [], "none", raw_html

        articles = _try_ai(resp.text, page_name, page_url, self._api_key, self.model)
        logger.info("  %s: %d articles via AI extraction", page_name, len(articles))
        return articles, "AI fallback", raw_html


# ---------------------------------------------------------------------------
# Strategy 1: JSON API
# ---------------------------------------------------------------------------

def _try_json(
    text: str,
    page_name: str,
    page_url: str,
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
            if item_id and "hackerone" in page_url.lower():
                url = f"https://hackerone.com/reports/{item_id}"
            elif item_id:
                url = f"{page_url.rstrip('/')}#{item_id}"
            else:
                url = page_url

        date_str = _get_json_field(
            item, ["date", "published_at", "created_at", "disclosed_at",
                   "published", "pubDate", "created", "timestamp"],
        )
        published = _parse_date(date_str)

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
# Strategy 3: Jina Reader (free Markdown extraction)
# ---------------------------------------------------------------------------

async def _try_jina(
    http: httpx.AsyncClient,
    page_name: str,
    page_url: str,
) -> list[Article]:
    jina_url = f"https://r.jina.ai/{page_url}"
    try:
        resp = await http.get(
            jina_url,
            headers={"User-Agent": "Mozilla/5.0 NewsletterAgent/2.0"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.debug("  %s: Jina Reader request failed", page_name)
        return []

    content = resp.text.strip()
    if len(content) < 200:
        logger.debug(
            "  %s: Jina Reader returned too little content (%d chars)",
            page_name, len(content),
        )
        return []

    return _parse_markdown_articles(content, page_name, page_url)


def _parse_markdown_articles(
    markdown: str,
    page_name: str,
    page_url: str,
) -> list[Article]:
    articles: list[Article] = []
    seen_urls: set[str] = set()

    # Extract Markdown links with heading context: ## [Title](url)  or  ## Title\n...[link](url)
    # Pattern 1: Markdown heading links like ## [Title](URL)
    for match in re.finditer(r'^#{1,4}\s+\[([^\]]+)\]\(([^)]+)\)', markdown, re.MULTILINE):
        title = match.group(1).strip()
        url = match.group(2).strip()
        if not title or len(title) < 5 or not url.startswith("http"):
            continue
        if is_junk_article_url(url):
            continue
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

    # Pattern 2: Standalone links [Title](URL) that look like article titles
    if len(articles) < 3:
        for match in re.finditer(r'\[([^\]]{10,})\]\((https?://[^)]+)\)', markdown):
            title = match.group(1).strip()
            url = match.group(2).strip()
            if url in seen_urls:
                continue
            if url == page_url:
                continue
            if is_junk_article_url(url):
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

    if len(articles) >= 3:
        return articles
    return []


# ---------------------------------------------------------------------------
# Strategy 4: Firecrawl (JS-heavy sites)
# ---------------------------------------------------------------------------

def _try_firecrawl(
    page_name: str,
    page_url: str,
) -> list[Article]:
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        return []

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        result = app.scrape(page_url, formats=["markdown"])
    except Exception:
        logger.debug("  %s: Firecrawl scrape failed", page_name, exc_info=True)
        return []

    markdown = ""
    if hasattr(result, "markdown"):
        markdown = result.markdown or ""
    elif isinstance(result, dict):
        markdown = result.get("markdown", "")
    if not markdown or len(markdown) < 200:
        return []

    return _parse_markdown_articles(markdown, page_name, page_url)


# ---------------------------------------------------------------------------
# Strategy 5: HTML structural extraction
# ---------------------------------------------------------------------------

def _try_html(
    html: str,
    page_name: str,
    page_url: str,
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
# Strategy 6: AI extraction (Claude Haiku)
# ---------------------------------------------------------------------------

def _try_ai(
    html: str,
    page_name: str,
    page_url: str,
    api_key: str,
    model: str = "claude-haiku-4-5",
) -> list[Article]:
    content = _html_to_text(html, page_url)
    if not content.strip():
        return []

    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH]

    prompt = AI_EXTRACTION_PROMPT.format(base_url=page_url, content=content)

    client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com")
    response = client.messages.create(
        model=model,
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
# Pagination: generic "next page" detection
# ---------------------------------------------------------------------------

_NEXT_LINK_TEXTS = frozenset({
    "next", "next page", "next →", "next»", "›", "»", "→",
    "older posts", "older entries", "older", "more",
    "next ›", "next ▸",
})


def _find_next_page_url(html: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # 1. <link rel="next"> (SEO standard)
    link_next = soup.find("link", rel="next")
    if link_next and isinstance(link_next, Tag) and link_next.get("href"):
        return urljoin(current_url, str(link_next["href"]))

    # 2. <a rel="next">
    a_next = soup.find("a", rel="next")
    if a_next and isinstance(a_next, Tag) and a_next.get("href"):
        return urljoin(current_url, str(a_next["href"]))

    # 3. Look inside pagination containers
    for container in soup.find_all(
        ["nav", "div", "ul"],
        class_=re.compile(r"paginat|pager|page-nav", re.I),
    ):
        url = _find_next_in_container(container, current_url)
        if url:
            return url

    # 4. Look for aria-label="next" or aria-label="Next page" anywhere
    for a in soup.find_all("a", href=True):
        aria = str(a.get("aria-label", "")).lower().strip()
        if aria in ("next", "next page"):
            href = str(a["href"])
            if href and not href.startswith(("#", "javascript:")):
                return urljoin(current_url, href)

    return None


def _find_next_in_container(container: Tag, current_url: str) -> str | None:
    for a in container.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        classes = " ".join(a.get("class", [])).lower()
        aria = str(a.get("aria-label", "")).lower().strip()

        if "prev" in classes or "prev" in aria:
            continue

        if text in _NEXT_LINK_TEXTS or aria in ("next", "next page"):
            href = str(a["href"])
            if href and not href.startswith(("#", "javascript:")):
                return urljoin(current_url, href)
    return None


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
