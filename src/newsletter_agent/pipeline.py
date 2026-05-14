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

        logger.info("Fetched %d total, %d new after dedup", len(all_articles), len(new_articles))
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
            logger.info("Ranking %d articles with %s...", len(new_articles), self.ranker.model)
            ranked = self.ranker.rank_batch(new_articles, self.config.interests)
        else:
            ranked = []

        ranked.sort(key=lambda a: list(Priority).index(a.priority) if a.priority else 99)

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
        self.state.save_digest(digest)
        self.state.prune_seen()
        self.state.save()

        return digest

    def run_send(self, dry_run: bool = False) -> Digest:
        """Full pipeline: fetch, rank, format, deliver."""
        digest = self.run_digest()

        if dry_run:
            html = render_digest_html(digest)
            output_path = f"data/digest_preview_{digest.date.strftime('%Y%m%d_%H%M%S')}.html"
            with open(output_path, "w") as f:
                f.write(html)
            logger.info("Dry run: HTML saved to %s", output_path)
        elif self.delivery:
            email_id = self.delivery.send_digest(digest)
            logger.info("Digest sent (email_id=%s)", email_id)
        else:
            logger.warning("Email delivery not configured, skipping send")

        return digest

    async def _fetch_all(self, sources: list, since: datetime) -> list[Article]:  # type: ignore[type-arg]
        tasks = [source.fetch(since=since) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles: list[Article] = []
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("Source '%s' failed: %s", source.name, result)
                self.state.update_source_meta(source.source_id, success=False, error=str(result))
            else:
                articles.extend(result)
                self.state.update_source_meta(
                    source.source_id, success=True, articles_fetched=len(result),
                )
                logger.info("  %s: %d articles", source.name, len(result))
        return articles

    def _deduplicate(self, articles: list[Article]) -> list[Article]:
        seen_urls: set[str] = set()
        new: list[Article] = []
        for article in articles:
            if article.url in seen_urls or self.state.is_seen(article.url):
                continue
            seen_urls.add(article.url)
            new.append(article)
        return new
