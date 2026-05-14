"""Pipeline orchestrator: fetch → deduplicate → rank → format → deliver."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from newsletter_agent.config import AppConfig
from newsletter_agent.delivery.email import EmailDelivery
from newsletter_agent.delivery.templates import render_digest_html
from newsletter_agent.models import Article, Digest, Priority
from newsletter_agent.ranking.ranker import ArticleRanker
from newsletter_agent.sources import get_enabled_sources
from newsletter_agent.state.store import StateStore
from newsletter_agent.utils import titles_similar

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, config: AppConfig, model_override: str | None = None):
        self.config = config
        self.state = StateStore(config.state_dir)
        self.ranker = ArticleRanker(
            model=model_override or config.llm.model,
            api_key=config.llm.api_key,
            max_batch_size=config.llm.max_articles_per_batch,
        )
        self.delivery: EmailDelivery | None = None
        if config.email.enabled and config.email.to_addresses:
            self.delivery = EmailDelivery(
                api_key=config.email.api_key,
                from_address=config.email.from_address,
                to_addresses=config.email.to_addresses,
            )

    def run_fetch(self) -> list[Article]:
        """Fetch from all sources and deduplicate."""
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config)
        logger.info("Fetching from %d sources...", len(sources))

        all_articles = asyncio.run(self._fetch_all(sources, since))
        new_articles = self._deduplicate(all_articles)

        logger.info(
            "Fetched %d total, %d new after dedup",
            len(all_articles), len(new_articles),
        )
        return new_articles

    def run_digest(self, model_override: str | None = None) -> Digest:
        """Fetch, rank, and build digest."""
        start = time.monotonic()
        since = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)
        sources = get_enabled_sources(self.config)

        logger.info("Fetching from %d sources...", len(sources))
        all_articles = asyncio.run(self._fetch_all(sources, since))
        new_articles = self._deduplicate(all_articles)
        logger.info("Fetched %d total, %d new", len(all_articles), len(new_articles))

        if new_articles:
            logger.info(
                "Ranking %d articles with %s...",
                len(new_articles), self.ranker.model,
            )
            ranked = self.ranker.rank_batch(new_articles, self.config.interests)
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
        self.state.prune_seen()
        self.state.save()

        return digest

    def run_send(self, dry_run: bool = False) -> Digest:
        """Full pipeline: fetch, rank, format, deliver."""
        digest = self.run_digest()

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
