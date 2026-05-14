"""Hacker News source via Firebase REST API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

HN_API = "https://hacker-news.firebaseio.com/v0"
CONCURRENCY = 10


class HackerNewsSource(BaseSource):
    def __init__(self, min_score: int = 50, max_stories: int = 100):
        self._min_score = min_score
        self._max_stories = max_stories

    @property
    def name(self) -> str:
        return "Hacker News"

    @property
    def source_id(self) -> str:
        return "hackernews"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{HN_API}/topstories.json")
            resp.raise_for_status()
            story_ids: list[int] = resp.json()[: self._max_stories]

            semaphore = asyncio.Semaphore(CONCURRENCY)

            async def fetch_item(item_id: int) -> dict | None:  # type: ignore[type-arg]
                async with semaphore:
                    try:
                        r = await client.get(f"{HN_API}/item/{item_id}.json")
                        r.raise_for_status()
                        return r.json()  # type: ignore[no-any-return]
                    except httpx.HTTPError:
                        return None

            results = await asyncio.gather(*(fetch_item(sid) for sid in story_ids))

        articles: list[Article] = []
        for item in results:
            if not item or item.get("type") != "story" or not item.get("url"):
                continue
            score = item.get("score", 0)
            if score < self._min_score:
                continue
            published = None
            if item.get("time"):
                published = datetime.fromtimestamp(item["time"], tz=UTC)
            if since and published and published < since:
                continue
            articles.append(Article(
                title=item.get("title", "Untitled"),
                url=item["url"],
                source_id=self.source_id,
                source_name=self.name,
                published_at=published,
                raw_summary="",
                score=score,
                extra={
                    "hn_id": str(item.get("id", "")),
                    "comments": str(item.get("descendants", 0)),
                },
            ))
        return articles
