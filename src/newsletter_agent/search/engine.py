"""Deep Search Engine — orchestrates all search layers in parallel."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic

from newsletter_agent.search import merger
from newsletter_agent.search.models import (
    LayerResult,
    QueryPlan,
    SearchEngineResult,
)
from newsletter_agent.search.query_generator import generate_queries

logger = logging.getLogger(__name__)


class DeepSearchEngine:
    def __init__(
        self,
        config: object,
        anthropic_api_key: str,
    ):
        from newsletter_agent.config import SearchConfig
        self._config: SearchConfig = config  # type: ignore[assignment]
        self._anthropic_client = anthropic.Anthropic(
            api_key=anthropic_api_key,
            base_url="https://api.anthropic.com",
        )

    def run(self, topic: str, about_me: str) -> SearchEngineResult:
        start = time.monotonic()
        domain_ctx = self._config.domain_context

        # Step 1: Generate query plan
        logger.info("Deep Search Engine starting for topic: %s", topic)
        query_plan = generate_queries(
            topic, about_me, self._anthropic_client,
            domain_context=domain_ctx,
        )
        categories = {q.category for q in query_plan.queries}
        logger.info(
            "Generated %d queries across %d categories",
            len(query_plan.queries), len(categories),
        )

        # Step 2: Run all enabled layers in parallel
        logger.info("Running search layers in parallel...")
        layer_results = self._run_layers(query_plan, topic, about_me)

        # Step 3: Log per-layer results
        for result in layer_results:
            if result.success:
                logger.info(
                    "Layer [%s]: %d results in %.1fs",
                    result.layer_name, len(result.results), result.duration_seconds,
                )
            else:
                logger.warning(
                    "Layer [%s]: FAILED — %s", result.layer_name, result.error,
                )

        # Step 4: Merge and deduplicate
        merged = merger.merge_and_deduplicate(layer_results)
        high_conf = sum(1 for r in merged if r.high_confidence)

        # Step 5: Build result
        total_raw = sum(len(r.results) for r in layer_results)
        duration = time.monotonic() - start
        cost = self._estimate_cost(layer_results, query_plan)

        logger.info(
            "Deep search complete: %d raw results -> %d unique URLs in %.1fs (~$%.2f)",
            total_raw, len(merged), duration, cost,
        )
        if high_conf:
            logger.info("High confidence (3+ layers): %d URLs", high_conf)

        return SearchEngineResult(
            topic=topic,
            query_plan=query_plan,
            layer_results=layer_results,
            merged_results=merged,
            total_urls_found=total_raw,
            unique_urls=len(merged),
            duration_seconds=duration,
            cost_estimate_usd=cost,
        )

    def _run_layers(
        self, query_plan: QueryPlan, topic: str, about_me: str,
    ) -> list[LayerResult]:
        results: list[LayerResult] = []
        domain_ctx = self._config.domain_context

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []

            # Layer 1A: Tavily
            if self._config.tavily.enabled:
                tavily_key = os.environ.get("TAVILY_API_KEY", "")
                if tavily_key:
                    from newsletter_agent.search.layer_tavily import TavilyLayer
                    layer = TavilyLayer(
                        api_key=tavily_key,
                        search_depth=self._config.tavily.search_depth,
                        max_results_per_query=self._config.tavily.max_results_per_query,
                        max_concurrent=self._config.tavily.max_concurrent_queries,
                    )
                    futures.append(executor.submit(
                        self._safe_run, "Tavily", layer.search, query_plan.queries,
                    ))
                else:
                    logger.info("TAVILY_API_KEY not set — skipping Tavily layer")

            # Layer 1B: Exa
            if self._config.exa.enabled:
                exa_key = os.environ.get("EXA_API_KEY", "")
                if exa_key:
                    from newsletter_agent.search.layer_exa import ExaLayer
                    layer_exa = ExaLayer(
                        api_key=exa_key,
                        max_results_per_query=self._config.exa.max_results_per_query,
                        max_concurrent=self._config.exa.max_concurrent_queries,
                    )
                    futures.append(executor.submit(
                        self._safe_run, "Exa", layer_exa.search, query_plan.queries,
                    ))
                else:
                    logger.info("EXA_API_KEY not set — skipping Exa layer")

            # Layer 2: Perplexity
            if self._config.perplexity.enabled:
                ppx_key = os.environ.get("PERPLEXITY_API_KEY", "")
                if ppx_key:
                    from newsletter_agent.search.layer_perplexity import (
                        PerplexityDeepResearchLayer,
                    )
                    layer_ppx = PerplexityDeepResearchLayer(
                        api_key=ppx_key,
                        model=self._config.perplexity.model,
                        prompts_to_run=self._config.perplexity.prompts_to_run,
                        max_concurrent=self._config.perplexity.max_concurrent,
                    )
                    futures.append(executor.submit(
                        self._safe_run, "Perplexity Deep",
                        layer_ppx.search, query_plan.queries,
                        topic, about_me, domain_ctx,
                    ))
                else:
                    logger.info("PERPLEXITY_API_KEY not set — skipping Perplexity layer")

            for future in futures:
                results.append(future.result())

        return results

    @staticmethod
    def _safe_run(
        layer_name: str, fn: object, *args: object,
    ) -> LayerResult:
        try:
            return fn(*args)  # type: ignore[operator,no-any-return]
        except Exception as e:
            logger.error("Layer [%s] crashed: %s", layer_name, e, exc_info=True)
            return LayerResult(
                layer_name=layer_name,
                results=[],
                query_count=0,
                success=False,
                error=str(e),
            )

    def _estimate_cost(
        self, layer_results: list[LayerResult], query_plan: QueryPlan,
    ) -> float:
        cost = 0.01  # query generation flat cost

        for lr in layer_results:
            if lr.layer_name == "Tavily":
                per_query = 0.016 if self._config.tavily.search_depth == "advanced" else 0.008
                cost += lr.query_count * per_query
            elif lr.layer_name == "Exa":
                cost += lr.query_count * 0.012
            elif lr.layer_name == "Perplexity Deep":
                cost += lr.query_count * 0.82

        return cost
