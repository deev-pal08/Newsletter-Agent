"""Generic RSS/Atom feed source. Handles multiple feeds from config."""

from __future__ import annotations

from datetime import UTC, datetime
from time import mktime
from typing import TYPE_CHECKING

import feedparser
import httpx

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

if TYPE_CHECKING:
    from newsletter_agent.report import RunReport


class RSSSource(BaseSource):
    def __init__(self, feeds: dict[str, str]):
        self._feeds = feeds

    @property
    def name(self) -> str:
        return "RSS Feeds"

    @property
    def source_id(self) -> str:
        return "rss"

    async def fetch(
        self,
        since: datetime | None = None,
        report: RunReport | None = None,
    ) -> list[Article]:
        articles: list[Article] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for feed_name, feed_url in self._feeds.items():
                try:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                    parsed = feedparser.parse(resp.text)
                    for entry in parsed.entries:
                        published = _parse_published(entry)
                        if since and published and published < since:
                            continue
                        articles.append(Article(
                            title=entry.get("title", "Untitled"),
                            url=entry.get("link", ""),
                            source_id=self.source_id,
                            source_name=feed_name,
                            published_at=published,
                            raw_summary=_extract_summary(entry),
                        ))
                    if report is not None:
                        report.add_feed_ok(feed_name)
                except Exception as e:
                    if report is not None:
                        report.add_feed_failed(feed_name, str(e))
                    continue
        return articles


def _parse_published(entry: dict) -> datetime | None:  # type: ignore[type-arg]
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(mktime(entry.published_parsed), tz=UTC)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(mktime(entry.updated_parsed), tz=UTC)
    return None


def _extract_summary(entry: dict) -> str:  # type: ignore[type-arg]
    summary = entry.get("summary", "")
    if not summary and hasattr(entry, "content"):
        contents = entry.get("content", [])
        if contents:
            summary = contents[0].get("value", "")
    if len(summary) > 500:
        summary = summary[:500] + "..."
    return summary
