"""oss-security mailing list source via web archive scraping."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from newsletter_agent.models import Article
from newsletter_agent.sources.base import BaseSource

BASE_URL = "https://www.openwall.com/lists/oss-security"


class OSSSecuritySource(BaseSource):
    @property
    def name(self) -> str:
        return "oss-security"

    @property
    def source_id(self) -> str:
        return "oss_security"

    async def fetch(self, since: datetime | None = None) -> list[Article]:
        now = datetime.now(UTC)

        articles: list[Article] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            # Fetch index for today and yesterday
            for day_offset in range(2):
                date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                date = date.replace(day=date.day - day_offset) if date.day > day_offset else date
                date_path = date.strftime("%Y/%m/%d")
                index_url = f"{BASE_URL}/{date_path}/"

                try:
                    resp = await client.get(index_url)
                    if resp.status_code != 200:
                        continue
                except httpx.HTTPError:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.select("a[href]"):
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    if not text or not href or href.startswith(".."):
                        continue
                    # Message links look like "1", "2", etc.
                    if not re.match(r"^\d+$", href):
                        continue

                    msg_url = f"{BASE_URL}/{date_path}/{href}"
                    cve_match = re.search(r"CVE-\d{4}-\d+", text)
                    tags = [cve_match.group()] if cve_match else []

                    articles.append(Article(
                        title=text[:200],
                        url=msg_url,
                        source_id=self.source_id,
                        source_name=self.name,
                        published_at=date,
                        raw_summary="",
                        tags=tags,
                    ))
        return articles
