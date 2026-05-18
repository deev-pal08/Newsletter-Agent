"""Layer 1B — Exa Neural Search."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from newsletter_agent.search.models import LayerResult, SearchQuery, SearchResult

logger = logging.getLogger(__name__)


class ExaLayer:
    def __init__(
        self,
        api_key: str,
        max_results_per_query: int = 10,
        max_concurrent: int = 5,
    ):
        from exa_py import Exa
        self._client = Exa(api_key=api_key)
        self._max_results = max_results_per_query
        self._max_concurrent = max_concurrent

    def search(self, queries: list[SearchQuery]) -> LayerResult:
        start = time.monotonic()
        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        def _run_query(q: SearchQuery) -> list[SearchResult]:
            search_type = "keyword" if q.category == "DEPTH" else "auto"
            try:
                response = self._client.search_and_contents(
                    query=q.query,
                    type=search_type,
                    num_results=self._max_results,
                    highlights=True,
                    text=True,
                )
                results = []
                for r in response.results:
                    url = getattr(r, "url", "")
                    if not url:
                        continue
                    highlights = getattr(r, "highlights", None)
                    description = ""
                    if highlights and isinstance(highlights, list):
                        description = " ".join(highlights)[:500]
                    full_text = getattr(r, "text", None)
                    results.append(SearchResult(
                        url=url,
                        title=getattr(r, "title", "") or "",
                        description=description,
                        source_layer="exa",
                        source_query=q.query,
                        query_category=q.category,
                        published_date=getattr(r, "published_date", None),
                        full_content=full_text,
                        score=getattr(r, "score", None),
                    ))
                return results
            except Exception:
                logger.warning("Exa query failed: %s", q.query, exc_info=True)
                return []

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            futures = {executor.submit(_run_query, q): q for q in queries}
            for future in as_completed(futures):
                for result in future.result():
                    if result.url not in seen_urls:
                        seen_urls.add(result.url)
                        all_results.append(result)

        duration = time.monotonic() - start
        logger.info("Exa: %d results in %.1fs", len(all_results), duration)
        return LayerResult(
            layer_name="Exa",
            results=all_results,
            query_count=len(queries),
            success=True,
            duration_seconds=duration,
        )
