"""Reddit source via public RSS feeds (no API key needed)."""

from __future__ import annotations

from datetime import UTC, datetime
from time import mktime

import feedparser
import httpx

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource


class RedditSource(BaseSource):
    def __init__(self, subreddits: list[str] | None = None):
        self._subreddits = subreddits or ["netsec", "bugbounty", "MachineLearning", "LocalLLaMA"]

    @property
    def name(self) -> str:
        return "Reddit"

    @property
    def source_id(self) -> str:
        return "reddit"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        articles: list[Article] = []
        headers = {"User-Agent": "newsletter-agent/0.1.0"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            for sub in self._subreddits:
                try:
                    resp = await client.get(f"https://www.reddit.com/r/{sub}/.rss")
                    resp.raise_for_status()
                    parsed = feedparser.parse(resp.text)
                    for entry in parsed.entries:
                        published = None
                        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
                            published = datetime.fromtimestamp(
                                mktime(entry.updated_parsed), tz=UTC
                            )
                        if since and published and published < since:
                            continue
                        articles.append(Article(
                            title=entry.get("title", "Untitled"),
                            url=entry.get("link", ""),
                            source_id=self.source_id,
                            source_name=f"r/{sub}",
                            published_at=published,
                            raw_summary=_clean_summary(entry.get("summary", "")),
                            extra={"subreddit": sub},
                        ))
                except (httpx.HTTPError, Exception):
                    continue
        return articles


def _clean_summary(html_summary: str) -> str:
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html_summary, "html.parser").get_text(separator=" ", strip=True)
    if len(text) > 500:
        text = text[:500] + "..."
    return text
