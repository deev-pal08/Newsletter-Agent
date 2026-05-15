"""Pipeline orchestrator: fetch → deduplicate → rank → format → deliver."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

from newsletter_agent.config import AppConfig, load_about_me
from newsletter_agent.delivery.email import EmailDelivery
from newsletter_agent.delivery.templates import render_digest_html
from newsletter_agent.models import Article, Digest, Priority
from newsletter_agent.ranking.ranker import ArticleRanker, BatchRanker
from newsletter_agent.sources import get_enabled_sources
from newsletter_agent.sources.web import (
    WebSource,
    collect_extraction_results,
    submit_extraction_batch,
)
from newsletter_agent.state.store import StateStore
from newsletter_agent.utils import titles_similar

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, config: AppConfig, model_override: str | None = None):
        self.config = config
        self.state = StateStore(config.state_dir)
        self.model = model_override or config.llm.model
        self.about_me = load_about_me(config.about_me)
        self._ranker: ArticleRanker | None = None
        self.delivery: EmailDelivery | None = None
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
            )
        return self._ranker

    def run_fetch(self) -> list[Article]:
        """Fetch from all sources and deduplicate."""
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config, self.state)
        logger.info("Fetching from %d sources...", len(sources))

        all_articles = asyncio.run(self._fetch_all(sources, since))
        new_articles = self._deduplicate(all_articles)

        logger.info(
            "Fetched %d total, %d new after dedup",
            len(all_articles), len(new_articles),
        )
        self.state.save()
        return new_articles

    def run_digest(self, use_batch: bool = False) -> Digest:
        """Fetch, rank, and build digest."""
        start = time.monotonic()
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config, self.state)

        logger.info("Fetching from %d sources...", len(sources))
        all_articles = asyncio.run(self._fetch_all(sources, since))
        new_articles = self._deduplicate(all_articles)
        logger.info("Fetched %d total, %d new", len(all_articles), len(new_articles))

        if new_articles:
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
        digest_id = self.state.save_digest(digest)
        digest.digest_id = digest_id
        self.state.save()

        return digest

    def run_batch_submit(self) -> str:
        """Fetch, dedup, and submit articles for async batch ranking.
        Returns the batch ID. Results are collected later with batch_collect().
        """
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config, self.state)

        # Enable deferred AI extraction on web sources
        for source in sources:
            if isinstance(source, WebSource):
                source.defer_ai = True

        logger.info("Fetching from %d sources...", len(sources))
        all_articles = asyncio.run(self._fetch_all(sources, since))
        new_articles = self._deduplicate(all_articles)
        logger.info("Fetched %d total, %d new", len(all_articles), len(new_articles))

        if not new_articles:
            logger.info("No new articles to rank")
            return ""

        batch_ranker = BatchRanker(
            model=self.model,
            api_key=self.config.llm.api_key,
            max_batch_size=self.config.llm.max_articles_per_batch,
        )
        batch_id = batch_ranker.submit(
            new_articles, self.config.interests, self.about_me,
        )

        # Submit web extraction batch if any pages need AI
        pending = []
        for source in sources:
            if isinstance(source, WebSource):
                pending.extend(source.pending_extractions)

        extraction_batch_id = ""
        if pending:
            try:
                extraction_batch_id = submit_extraction_batch(
                    pending, self.config.llm.api_key,
                )
                self.state._set_meta(
                    "extraction_batch_id", extraction_batch_id,
                )
                self.state._set_meta(
                    "extraction_pending",
                    json.dumps(pending),
                )
            except Exception:
                logger.exception("Failed to submit web extraction batch")

        # Mark articles as seen now (they'll be ranked later)
        for article in new_articles:
            self.state.mark_seen(article)
        self.state.save()

        # Save batch job so we can collect results later
        self.state.save_batch_job(batch_id, new_articles, self.config.interests)
        logger.info("Batch %s submitted with %d articles", batch_id, len(new_articles))
        if extraction_batch_id:
            logger.info(
                "Extraction batch %s submitted with %d pages",
                extraction_batch_id, len(pending),
            )
        return batch_id

    def run_batch_collect(self, batch_id: str | None = None) -> Digest | None:
        """Check a pending batch and build digest if results are ready."""
        if batch_id is None:
            pending = self.state.get_pending_batch()
            if not pending:
                logger.info("No pending batch jobs")
                return None
            batch_id = pending["batch_id"]

        batch_ranker = BatchRanker(
            model=self.model,
            api_key=self.config.llm.api_key,
            max_batch_size=self.config.llm.max_articles_per_batch,
        )

        status = batch_ranker.check_status(batch_id)
        logger.info("Batch %s status: %s", batch_id, status)

        if status != "ended":
            if status in ("canceled", "expired"):
                self.state.update_batch_status(batch_id, status)
            return None

        articles = self.state.get_batch_articles(batch_id)
        ranked = batch_ranker.collect_results(batch_id, articles)

        # Collect web extraction results if a batch was submitted
        extraction_batch_id = self.state._get_meta("extraction_batch_id")
        if extraction_batch_id:
            try:
                ext_status = batch_ranker.check_status(extraction_batch_id)
                if ext_status == "ended":
                    pending_json = self.state._get_meta("extraction_pending") or "[]"
                    pending_meta = json.loads(pending_json)
                    since = datetime.now(UTC) - timedelta(
                        hours=self.config.lookback_hours,
                    )
                    extracted = collect_extraction_results(
                        extraction_batch_id, pending_meta,
                        self.config.llm.api_key, since,
                    )
                    # Deduplicate extracted articles against ranked ones
                    ranked_urls = {a.normalized_url for a in ranked}
                    for a in extracted:
                        if a.normalized_url not in ranked_urls:
                            a.priority = Priority.REFERENCE
                            a.ai_summary = "Extracted via web AI (unranked)"
                            ranked.append(a)
                            self.state.mark_seen(a)
                    logger.info(
                        "Added %d articles from web extraction batch",
                        len(extracted),
                    )
                else:
                    logger.warning(
                        "Web extraction batch %s not ready: %s",
                        extraction_batch_id, ext_status,
                    )
            except Exception:
                logger.exception("Failed to collect web extraction results")
            finally:
                self.state._set_meta("extraction_batch_id", "")
                self.state._set_meta("extraction_pending", "")

        ranked.sort(
            key=lambda a: list(Priority).index(a.priority) if a.priority else 99,
        )

        digest = Digest(
            date=datetime.now(UTC),
            articles=ranked,
            sources_used=[],
            total_fetched=len(articles),
            total_after_dedup=len(articles),
            generation_time_seconds=0,
        )

        digest_id = self.state.save_digest(digest)
        digest.digest_id = digest_id
        self.state.update_batch_status(batch_id, "ended")
        self.state.save()

        return digest

    def run_send(self, dry_run: bool = False, use_batch: bool = False) -> Digest:
        """Full pipeline: fetch, rank, format, deliver."""
        digest = self.run_digest(use_batch=use_batch)

        if dry_run:
            html = render_digest_html(digest)
            out = f"data/digest_preview_{digest.date.strftime('%Y%m%d_%H%M%S')}.html"
            with open(out, "w") as f:
                f.write(html)
            logger.info("Dry run: HTML saved to %s", out)
        elif self.delivery:
            email_id = self.delivery.send_digest(digest)
            digest.email_sent = True
            digest.email_id = email_id
            if digest.digest_id:
                self.state.update_digest_email(digest.digest_id, email_id)
            logger.info("Digest sent (email_id=%s)", email_id)
        else:
            logger.warning("Email delivery not configured, skipping send")

        return digest

    def _rank_batch_api(self, articles: list[Article]) -> list[Article]:
        """Rank using Batch API (submit and poll until complete)."""
        batch_ranker = BatchRanker(
            model=self.model,
            api_key=self.config.llm.api_key,
            max_batch_size=self.config.llm.max_articles_per_batch,
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
                continue
            healthy_sources.append(source)

        tasks = [source.fetch(since=since) for source in healthy_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles: list[Article] = []
        for source, result in zip(healthy_sources, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("Source '%s' failed: %s", source.name, result)
                self.state.update_source_meta(
                    source.source_id, success=False, error=str(result),
                )
            else:
                articles.extend(result)
                self.state.update_source_meta(
                    source.source_id,
                    success=True,
                    articles_fetched=len(result),
                )
                logger.info("  %s: %d articles", source.name, len(result))
        return articles

    def _deduplicate(self, articles: list[Article]) -> list[Article]:
        seen_normalized: set[str] = set()
        new: list[Article] = []
        threshold = self.config.dedup.title_similarity_threshold

        for article in articles:
            norm = article.normalized_url
            # Check normalized URL against in-batch and historical state
            if norm in seen_normalized or self.state.is_seen_normalized(norm):
                continue

            # Check exact title fingerprint in DB
            if article.title_fp and self.state.find_similar_title(article.title_fp):
                continue

            # Check title similarity against current batch
            if self.config.dedup.fuzzy_url and any(
                titles_similar(article.title, existing.title, threshold)
                for existing in new
                if article.source_id != existing.source_id
            ):
                continue

            seen_normalized.add(norm)
            new.append(article)
        return new
