"""Claude API integration for article ranking (sync and batch modes)."""

from __future__ import annotations

import json
import logging
import os
import time

import anthropic

from newsletter_agent.models import Article, Priority
from newsletter_agent.ranking.prompts import (
    RANKING_SYSTEM_PROMPT,
    RANKING_USER_PROMPT_TEMPLATE,
    RANKING_USER_PROMPT_WITH_PROFILE_TEMPLATE,
    format_articles_for_ranking,
)

logger = logging.getLogger(__name__)

PRIORITY_MAP = {
    "CRITICAL_ACT_NOW": Priority.CRITICAL,
    "IMPORTANT_READ_THIS_WEEK": Priority.IMPORTANT,
    "INTERESTING_QUEUE_FOR_WEEKEND": Priority.INTERESTING,
    "REFERENCE_SAVE_FOR_LATER": Priority.REFERENCE,
}


def _build_article_dicts(articles: list[Article]) -> list[dict[str, str]]:
    return [
        {
            "id": a.id,
            "title": a.title,
            "source": a.source_name,
            "summary": a.raw_summary[:300],
            "url": a.url,
        }
        for a in articles
    ]


def _build_user_prompt(
    articles: list[Article],
    user_interests: list[str],
    user_profile: str = "",
) -> str:
    article_dicts = _build_article_dicts(articles)
    articles_text = format_articles_for_ranking(article_dicts)
    if user_profile:
        return RANKING_USER_PROMPT_WITH_PROFILE_TEMPLATE.format(
            profile=user_profile,
            interests=", ".join(user_interests),
            count=len(articles),
            articles_text=articles_text,
        )
    return RANKING_USER_PROMPT_TEMPLATE.format(
        interests=", ".join(user_interests),
        count=len(articles),
        articles_text=articles_text,
    )


def parse_rankings(text: str) -> list[dict[str, str]]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.warning("Failed to parse ranking response as JSON")

    return []


def apply_rankings(articles: list[Article], rankings: list[dict[str, str]]) -> list[Article]:
    ranking_by_id = {r["id"]: r for r in rankings}
    for article in articles:
        ranking = ranking_by_id.get(article.id)
        if ranking:
            priority_str = ranking.get("priority", "REFERENCE_SAVE_FOR_LATER")
            article.priority = PRIORITY_MAP.get(priority_str, Priority.REFERENCE)
            article.ai_summary = ranking.get("summary", "")
            article.tags = ranking.get("tags", article.tags)
        else:
            article.priority = Priority.REFERENCE
            article.ai_summary = "Not ranked by AI"
    return articles


class ArticleRanker:
    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        api_key: str | None = None,
        max_batch_size: int = 100,
    ):
        self.model = model
        self.max_batch_size = max_batch_size
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    def rank_batch(
        self,
        articles: list[Article],
        user_interests: list[str],
        user_profile: str = "",
    ) -> list[Article]:
        if not articles:
            return []

        all_ranked: list[Article] = []
        for i in range(0, len(articles), self.max_batch_size):
            batch = articles[i : i + self.max_batch_size]
            ranked = self._rank_single_batch(batch, user_interests, user_profile)
            all_ranked.extend(ranked)
        return all_ranked

    def _rank_single_batch(
        self,
        articles: list[Article],
        user_interests: list[str],
        user_profile: str = "",
    ) -> list[Article]:
        user_prompt = _build_user_prompt(articles, user_interests, user_profile)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=RANKING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            response_text = response.content[0].text  # type: ignore[union-attr]
            rankings = parse_rankings(response_text)
        except Exception:
            logger.exception("Claude API call failed, assigning default priority")
            for a in articles:
                a.priority = Priority.REFERENCE
                a.ai_summary = "Ranking unavailable"
            return articles

        return apply_rankings(articles, rankings)


class BatchRanker:
    """Submits ranking jobs via Claude's Batch API (50% cheaper, async)."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        api_key: str | None = None,
        max_batch_size: int = 100,
    ):
        self.model = model
        self.max_batch_size = max_batch_size
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
        )

    def submit(
        self,
        articles: list[Article],
        user_interests: list[str],
        user_profile: str = "",
    ) -> str:
        """Submit articles for batch ranking. Returns the batch ID."""
        requests = []
        for i in range(0, len(articles), self.max_batch_size):
            chunk = articles[i : i + self.max_batch_size]
            user_prompt = _build_user_prompt(chunk, user_interests, user_profile)
            requests.append({
                "custom_id": f"ranking-chunk-{i}",
                "params": {
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": RANKING_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            })

        batch = self.client.messages.batches.create(requests=requests)
        logger.info("Batch submitted: %s (%d requests)", batch.id, len(requests))
        return batch.id

    def check_status(self, batch_id: str) -> str:
        """Check batch status. Returns: 'in_progress', 'ended', 'canceled', etc."""
        batch = self.client.messages.batches.retrieve(batch_id)
        return batch.processing_status

    def collect_results(self, batch_id: str, articles: list[Article]) -> list[Article]:
        """Download results from a completed batch and apply rankings."""
        all_rankings: list[dict[str, str]] = []
        for result in self.client.messages.batches.results(batch_id):
            if result.result.type == "succeeded":
                text = result.result.message.content[0].text  # type: ignore[union-attr]
                all_rankings.extend(parse_rankings(text))
            else:
                logger.warning(
                    "Batch request %s failed: %s",
                    result.custom_id, result.result.type,
                )

        return apply_rankings(articles, all_rankings)

    def submit_and_poll(
        self,
        articles: list[Article],
        user_interests: list[str],
        user_profile: str = "",
        poll_interval: int = 30,
        max_wait: int = 3600,
    ) -> list[Article]:
        """Submit, poll until complete, and return ranked articles."""
        batch_id = self.submit(articles, user_interests, user_profile)
        logger.info("Waiting for batch %s to complete...", batch_id)

        elapsed = 0
        while elapsed < max_wait:
            status = self.check_status(batch_id)
            if status == "ended":
                logger.info("Batch %s completed after %ds", batch_id, elapsed)
                return self.collect_results(batch_id, articles)
            if status in ("canceled", "expired"):
                logger.error("Batch %s %s", batch_id, status)
                for a in articles:
                    a.priority = Priority.REFERENCE
                    a.ai_summary = f"Batch {status}"
                return articles
            time.sleep(poll_interval)
            elapsed += poll_interval

        logger.error("Batch %s timed out after %ds", batch_id, max_wait)
        for a in articles:
            a.priority = Priority.REFERENCE
            a.ai_summary = "Batch timed out"
        return articles
