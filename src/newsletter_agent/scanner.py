"""Web article scanner: discovers fresh articles/data via Tavily Search."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from openai import OpenAI
from tavily import TavilyClient

from newsletter_agent.models import Article

if TYPE_CHECKING:
    from newsletter_agent.config import AppConfig
    from newsletter_agent.report import RunReport

logger = logging.getLogger(__name__)

QUERY_GEN_PROMPT = """\
You are a search query generator for a personalized newsletter agent.

Given a user profile and their interest areas, generate exactly {num_queries} \
diverse web search queries that will find the most relevant, recent articles, \
research, tools, and news for this user.

Rules:
- Each query should focus on a DIFFERENT interest area or goal
- Queries should be specific enough to find high-quality results, not generic
- Include the current year ({year}) in each query for recency
- Mix query types: some for breaking news/CVEs, some for research papers, \
some for new tools/releases, some for deep technical content
- Keep each query under 15 words
- Return ONLY a JSON array of strings, no explanation

User profile:
{about_me}

Interest areas: {interests}"""


def _generate_queries_llm(
    about_me: str,
    interests: list[str],
    num_queries: int = 5,
) -> list[str] | None:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    year = datetime.now(UTC).year
    prompt = QUERY_GEN_PROMPT.format(
        num_queries=num_queries,
        year=year,
        about_me=about_me or "Not provided",
        interests=", ".join(interests) if interests else "general technology",
    )

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        queries: list[str] = json.loads(text)
        return queries[:num_queries]
    except Exception:
        logger.warning("LLM query generation failed, using fallback", exc_info=True)
        return None


def _generate_queries_fallback(
    about_me: str,
    interests: list[str],
    num_queries: int = 5,
) -> list[str]:
    queries = []
    year = datetime.now(UTC).year

    for interest in interests[:num_queries]:
        queries.append(f"{interest} latest news research {year}")

    if about_me and len(queries) < num_queries:
        keywords = about_me.split()[:15]
        queries.append(f"{' '.join(keywords)} articles {year}")

    while len(queries) < num_queries:
        queries.append(f"technology security research news {year}")

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
        num_queries = discovery.tavily_queries_per_scan

        queries = _generate_queries_llm(
            self.about_me,
            self.config.interests,
            num_queries=num_queries,
        )
        if queries is None:
            queries = _generate_queries_fallback(
                self.about_me,
                self.config.interests,
                num_queries=num_queries,
            )
            logger.info("Using fallback query generation")

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
