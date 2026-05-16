"""Web article scanner: discovers fresh articles/data via Tavily Search."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tavily import TavilyClient

from newsletter_agent.models import Article

if TYPE_CHECKING:
    from newsletter_agent.config import AppConfig
    from newsletter_agent.report import RunReport

logger = logging.getLogger(__name__)


def _generate_search_queries(
    about_me: str,
    interests: list[str],
    num_queries: int = 3,
) -> list[str]:
    """Generate search queries from the user's profile and interests."""
    queries = []
    year = datetime.now(UTC).year

    if interests:
        mid = len(interests) // 2
        group1 = interests[:mid] if mid > 0 else interests
        group2 = interests[mid:] if mid > 0 else []

        queries.append(
            f"{' '.join(group1)} latest vulnerabilities CVE research {year}"
        )
        if group2:
            queries.append(
                f"{' '.join(group2)} new papers tools reports {year}"
            )

    if about_me:
        keywords = about_me.split()[:15]
        queries.append(f"{' '.join(keywords)} blog posts talks articles")

    while len(queries) < num_queries and interests:
        queries.append(
            f"{interests[0]} latest developments writeups advisories"
        )

    return queries[:num_queries]


class ArticleScanner:
    """Searches the web for articles matching user profile via Tavily."""

    def __init__(self, config: AppConfig, about_me: str = ""):
        self.config = config
        self.about_me = about_me

    def search(self, report: RunReport | None = None) -> list[Article]:
        """Search the web for articles via Tavily. Returns Article objects."""
        tavily_key = os.environ.get("TAVILY_API_KEY", "")
        if not tavily_key:
            logger.info(
                "TAVILY_API_KEY not set — skipping web article search"
            )
            if report is not None:
                report.tavily_skipped = "TAVILY_API_KEY not set"
            return []

        tavily = TavilyClient(api_key=tavily_key)
        discovery = self.config.discovery

        queries = _generate_search_queries(
            self.about_me,
            self.config.interests,
            num_queries=discovery.tavily_queries_per_scan,
        )

        articles: list[Article] = []
        seen_urls: set[str] = set()

        for query in queries:
            logger.info("Tavily article search: %s", query)
            kwargs: dict[str, object] = {
                "query": query,
                "search_depth": discovery.search_depth,
                "max_results": 10,
                "topic": "news",
            }
            if discovery.include_domains:
                kwargs["include_domains"] = discovery.include_domains
            if discovery.exclude_domains:
                kwargs["exclude_domains"] = discovery.exclude_domains

            try:
                response = tavily.search(**kwargs)
                query_count = 0
                for r in response.get("results", []):
                    url = r.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    query_count += 1

                    articles.append(Article(
                        title=r.get("title", ""),
                        url=url,
                        source_id="web_search",
                        source_name="Web Search",
                        raw_summary=r.get("content", "")[:500],
                        published_at=datetime.now(UTC),
                    ))
                if report is not None:
                    report.add_tavily_ok(query_count)
            except Exception as e:
                logger.exception(
                    "Tavily search failed for query: %s", query,
                )
                if report is not None:
                    report.add_tavily_failed(query, str(e))

        logger.info(
            "Tavily found %d articles across %d queries",
            len(articles), len(queries),
        )
        return articles
