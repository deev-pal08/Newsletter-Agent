"""Layer 1A — Tavily Advanced Search."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tavily import TavilyClient

from newsletter_agent.search.models import LayerResult, SearchQuery, SearchResult

logger = logging.getLogger(__name__)


class TavilyLayer:
    def __init__(
        self,
        api_key: str,
        search_depth: str = "advanced",
        max_results_per_query: int = 10,
        max_concurrent: int = 5,
    ):
        self._client = TavilyClient(api_key=api_key)
        self._search_depth = search_depth
        self._max_results = max_results_per_query
        self._max_concurrent = max_concurrent

    def search(self, queries: list[SearchQuery]) -> LayerResult:
        start = time.monotonic()
        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        def _run_query(q: SearchQuery) -> list[SearchResult]:
            try:
                response = self._client.search(
                    query=q.query,
                    search_depth=self._search_depth,
                    max_results=self._max_results,
                )
                results = []
                for r in response.get("results", []):
                    url = r.get("url", "")
                    if not url:
                        continue
                    results.append(SearchResult(
                        url=url,
                        title=r.get("title", ""),
                        description=r.get("content", "")[:500],
                        source_layer="tavily",
                        source_query=q.query,
                        query_category=q.category,
                        published_date=r.get("published_date"),
                        score=r.get("score"),
                    ))
                return results
            except Exception:
                logger.warning("Tavily query failed: %s", q.query, exc_info=True)
                return []

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            futures = {executor.submit(_run_query, q): q for q in queries}
            for future in as_completed(futures):
                for result in future.result():
                    if result.url not in seen_urls:
                        seen_urls.add(result.url)
                        all_results.append(result)

        duration = time.monotonic() - start
        logger.info("Tavily: %d results in %.1fs", len(all_results), duration)
        return LayerResult(
            layer_name="Tavily",
            results=all_results,
            query_count=len(queries),
            success=True,
            duration_seconds=duration,
        )
