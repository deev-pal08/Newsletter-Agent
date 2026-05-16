"""Pipeline orchestrator: fetch → deduplicate → rank → format → deliver."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from newsletter_agent.config import AppConfig, load_about_me
from newsletter_agent.cost_tracker import CostBreakdown
from newsletter_agent.delivery.email import EmailDelivery
from newsletter_agent.report import RunReport
from newsletter_agent.delivery.templates import render_digest_html
from newsletter_agent.models import Article, Digest, Priority
from newsletter_agent.ranking.filter import filter_articles
from newsletter_agent.ranking.ranker import ArticleRanker, BatchRanker
from newsletter_agent.scanner import ArticleScanner
from newsletter_agent.sources import get_enabled_sources
from newsletter_agent.state.store import StateStore
from newsletter_agent.utils import find_semantic_duplicates

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, config: AppConfig, model_override: str | None = None):
        self.config = config
        self.state = StateStore(config.state_dir)
        self.model = model_override or config.llm.model
        self.about_me = load_about_me(config.about_me)
        self._ranker: ArticleRanker | None = None
        self.delivery: EmailDelivery | None = None
        self.cost = CostBreakdown()
        self.report = RunReport()
        if config.email.enabled and config.email.to_addresses:
            try:
                self.delivery = EmailDelivery(
                    api_key=config.email.api_key,
                    from_address=config.email.from_address,
                    to_addresses=config.email.to_addresses,
                )
            except ValueError:
                self.delivery = None

    @property
    def ranker(self) -> ArticleRanker:
        if self._ranker is None:
            self._ranker = ArticleRanker(
                model=self.model,
                api_key=self.config.llm.api_key,
                max_batch_size=self.config.llm.max_articles_per_batch,
                prompt_caching=self.config.llm.prompt_caching,
            )
        return self._ranker

    def run_digest(self) -> Digest:
        """Fetch, search web, rank, and build digest."""
        self.cost = CostBreakdown()
        self.report = RunReport()
        start = time.monotonic()
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config, self.state)

        logger.info("Fetching from %d sources...", len(sources))
        all_articles = asyncio.run(self._fetch_all(sources, since, self.report))

        # Web article search via Tavily
        scanner = ArticleScanner(self.config, about_me=self.about_me)
        web_articles = scanner.search(report=self.report)
        if web_articles:
            logger.info("Tavily added %d articles", len(web_articles))
            all_articles.extend(web_articles)
            self.cost.add_tavily(
                self.config.discovery.tavily_queries_per_scan,
                self.config.discovery.search_depth,
            )

        new_articles = self._deduplicate(all_articles, self.report)
        logger.info("Fetched %d total, %d new", len(all_articles), len(new_articles))

        if new_articles:
            # Filter: remove noise before expensive ranking
            if self.config.filtering.enabled:
                pre_filter = len(new_articles)
                new_articles = filter_articles(
                    new_articles,
                    interests=self.config.interests,
                    about_me=self.about_me,
                    model=self.config.filtering.model,
                    fail_open=self.config.filtering.fail_open,
                    report=self.report,
                )
                self.cost.add_filter(pre_filter)

            use_batch = self.config.llm.use_batch
            self.report.ranking_mode = "batch" if use_batch else "sync"
            if use_batch:
                ranked = self._rank_batch_api(new_articles)
            else:
                logger.info(
                    "Ranking %d articles with %s...",
                    len(new_articles), self.model,
                )
                ranked = self.ranker.rank_batch(
                    new_articles, self.config.interests, self.about_me,
                )
            self.cost.add_ranking(len(new_articles), self.model, batch=use_batch)
        else:
            ranked = []

        ranked.sort(
            key=lambda a: list(Priority).index(a.priority) if a.priority else 99,
        )

        digest = Digest(
            date=datetime.now(UTC),
            articles=ranked,
            sources_used=[s.name for s in sources],
            total_fetched=len(all_articles),
            total_after_dedup=len(new_articles),
            generation_time_seconds=time.monotonic() - start,
        )

        # Persist state
        for article in new_articles:
            self.state.mark_seen(article)
        digest_id = self.state.save_digest(digest, cost_breakdown=self.cost.to_json())
        digest.digest_id = digest_id
        self.state.save()

        return digest

    def run_send(self, dry_run: bool = False) -> Digest:
        """Full pipeline: fetch, search web, rank, format, deliver."""
        digest = self.run_digest()

        if dry_run:
            html = render_digest_html(digest)
            out = f"data/digest_preview_{digest.date.strftime('%Y%m%d_%H%M%S')}.html"
            with open(out, "w") as f:
                f.write(html)
            logger.info("Dry run: HTML saved to %s", out)
            self.report.delivery_skipped = "dry run"
        elif self.delivery:
            try:
                email_id = self.delivery.send_digest(digest)
                digest.email_sent = True
                digest.email_id = email_id
                if digest.digest_id:
                    self.state.update_digest_email(digest.digest_id, email_id)
                logger.info("Digest sent (email_id=%s)", email_id)
                self.report.delivery_ok = True
            except Exception as e:
                logger.error("Email delivery failed: %s", e)
                self.report.delivery_error = str(e)
        else:
            logger.warning("Email delivery not configured, skipping send")
            self.report.delivery_skipped = "not configured"

        return digest

    def _rank_batch_api(self, articles: list[Article]) -> list[Article]:
        """Rank using Batch API (submit and poll until complete)."""
        batch_ranker = BatchRanker(
            model=self.model,
            api_key=self.config.llm.api_key,
            max_batch_size=self.config.llm.max_articles_per_batch,
            prompt_caching=self.config.llm.prompt_caching,
        )
        logger.info(
            "Ranking %d articles with %s via Batch API (50%% cheaper)...",
            len(articles), self.model,
        )
        return batch_ranker.submit_and_poll(
            articles, self.config.interests, self.about_me,
        )

    async def _fetch_all(
        self, sources: list, since: datetime,  # type: ignore[type-arg]
        report: RunReport | None = None,
    ) -> list[Article]:
        # Filter out unhealthy sources
        healthy_sources = []
        max_fail = self.config.health.max_consecutive_failures
        retry_h = self.config.health.retry_after_hours
        for source in sources:
            if self.config.health.auto_disable and not self.state.is_source_healthy(
                source.source_id, max_failures=max_fail, retry_after_hours=retry_h,
            ):
                logger.warning(
                    "Skipping '%s': disabled after %d consecutive failures",
                    source.name, max_fail,
                )
                if report is not None:
                    report.add_source_skipped(
                        source.name,
                        f"disabled after {max_fail} consecutive failures",
                    )
                continue
            healthy_sources.append(source)

        tasks = [source.fetch(since=since, report=report) for source in healthy_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles: list[Article] = []
        for source, result in zip(healthy_sources, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("Source '%s' failed: %s", source.name, result)
                self.state.update_source_meta(
                    source.source_id, success=False, error=str(result),
                )
                if report is not None:
                    report.add_source_failed(source.name, str(result))
            else:
                articles.extend(result)
                self.state.update_source_meta(
                    source.source_id,
                    success=True,
                    articles_fetched=len(result),
                )
                logger.info("  %s: %d articles", source.name, len(result))
                if report is not None:
                    report.add_source_ok(source.name, len(result))
        return articles

    def _deduplicate(
        self, articles: list[Article], report: RunReport | None = None,
    ) -> list[Article]:
        seen_normalized: set[str] = set()
        new: list[Article] = []

        for article in articles:
            norm = article.normalized_url
            if norm in seen_normalized or self.state.is_seen_normalized(norm):
                continue

            if article.title_fp and self.state.find_similar_title(article.title_fp):
                continue

            seen_normalized.add(norm)
            new.append(article)

        dedup_by_url = len(articles) - len(new)

        # Semantic dedup pass (cross-source, within current batch)
        if self.config.dedup.use_semantic and len(new) >= 2:
            try:
                import os
                if os.environ.get("OPENAI_API_KEY"):
                    titles = [a.title for a in new]
                    dup_indices = find_semantic_duplicates(
                        titles,
                        threshold=self.config.dedup.semantic_threshold,
                        model=self.config.dedup.embedding_model,
                        state_store=self.state,
                        cache_enabled=self.config.dedup.cache_embeddings,
                    )
                    if dup_indices:
                        before = len(new)
                        new = [a for i, a in enumerate(new) if i not in dup_indices]
                        semantic_removed = before - len(new)
                        logger.info(
                            "Semantic dedup removed %d articles", semantic_removed,
                        )
                        if report is not None:
                            report.dedup_semantic = True
                            report.dedup_removed = dedup_by_url + semantic_removed
                    elif report is not None:
                        report.dedup_semantic = True
                        report.dedup_removed = dedup_by_url
                else:
                    logger.info("OPENAI_API_KEY not set — using title similarity dedup")
                    if report is not None:
                        report.dedup_fallback = True
                        report.dedup_removed = dedup_by_url
            except Exception:
                logger.warning("Semantic dedup failed, falling back to difflib", exc_info=True)
                if report is not None:
                    report.dedup_fallback = True
                    report.dedup_removed = dedup_by_url
        elif report is not None:
            report.dedup_removed = dedup_by_url

        return new
