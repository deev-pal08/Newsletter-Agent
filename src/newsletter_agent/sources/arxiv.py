"""arXiv API source for security and AI papers."""

from __future__ import annotations

from datetime import UTC, datetime
from time import mktime

import feedparser
import httpx

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

ARXIV_API_URL = "https://export.arxiv.org/api/query"


class ArxivSource(BaseSource):
    def __init__(self, categories: list[str] | None = None, max_results: int = 50):
        self._categories = categories or ["cs.CR", "cs.AI", "cs.LG"]
        self._max_results = max_results

    @property
    def name(self) -> str:
        return "arXiv"

    @property
    def source_id(self) -> str:
        return "arxiv"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        query = " OR ".join(f"cat:{cat}" for cat in self._categories)
        params = {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": str(self._max_results),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()

        parsed = feedparser.parse(resp.text)
        articles: list[Article] = []
        for entry in parsed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime.fromtimestamp(mktime(entry.published_parsed), tz=UTC)
            if since and published and published < since:
                continue

            categories = [t.get("term", "") for t in entry.get("tags", [])]
            authors = ", ".join(a.get("name", "") for a in entry.get("authors", []))

            articles.append(Article(
                title=entry.get("title", "Untitled").replace("\n", " "),
                url=entry.get("link", ""),
                source_id=self.source_id,
                source_name=self.name,
                published_at=published,
                raw_summary=entry.get("summary", "").replace("\n", " ")[:500],
                tags=categories,
                extra={"authors": authors},
            ))
        return articles
