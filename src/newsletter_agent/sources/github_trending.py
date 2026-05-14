"""GitHub trending repos via HTML scraping."""

from __future__ import annotations

from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

TRENDING_URL = "https://github.com/trending"


class GitHubTrendingSource(BaseSource):
    @property
    def name(self) -> str:
        return "GitHub Trending"

    @property
    def source_id(self) -> str:
        return "github_trending"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(TRENDING_URL, params={"since": "daily"})
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        articles: list[Article] = []

        for row in soup.select("article.Box-row"):
            name_el = row.select_one("h2 a")
            if not name_el:
                continue
            repo_path = name_el.get("href", "").strip()
            if not repo_path:
                continue
            repo_name = repo_path.strip("/")
            url = f"https://github.com{repo_path}"

            desc_el = row.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            lang_el = row.select_one("[itemprop='programmingLanguage']")
            language = lang_el.get_text(strip=True) if lang_el else ""

            stars_today = ""
            star_el = row.select_one("span.d-inline-block.float-sm-right")
            if star_el:
                stars_today = star_el.get_text(strip=True)

            articles.append(Article(
                title=repo_name,
                url=url,
                source_id=self.source_id,
                source_name=self.name,
                raw_summary=description,
                tags=[language] if language else [],
                extra={"stars_today": stars_today, "language": language},
            ))

        return articles
