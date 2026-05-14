"""Conference proceedings tracker (Black Hat, DEF CON, USENIX)."""

from __future__ import annotations

from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

CONFERENCE_URLS = {
    "Black Hat": "https://www.blackhat.com/upcoming.html",
    "DEF CON": "https://defcon.org/html/links/dc-cfp.html",
    "USENIX Security": "https://www.usenix.org/conferences/byname/108",
}


class ConferencesSource(BaseSource):
    @property
    def name(self) -> str:
        return "Conferences"

    @property
    def source_id(self) -> str:
        return "conferences"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        articles: list[Article] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for conf_name, url in CONFERENCE_URLS.items():
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for link in soup.select("a[href]"):
                        text = link.get_text(strip=True)
                        href = link.get("href", "")
                        if not text or len(text) < 10 or len(text) > 200:
                            continue
                        if not href.startswith("http"):
                            href = url.rsplit("/", 1)[0] + "/" + href
                        articles.append(Article(
                            title=f"[{conf_name}] {text}",
                            url=href,
                            source_id=self.source_id,
                            source_name=conf_name,
                            raw_summary="",
                            tags=[conf_name.lower().replace(" ", "-")],
                        ))
                except (httpx.HTTPError, Exception):
                    continue
        return articles
