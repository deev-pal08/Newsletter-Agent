"""Claude API integration for batch article ranking."""

from __future__ import annotations

import json
import logging
import os

import anthropic

from newsletter_agent.models import Article, Priority
from newsletter_agent.ranking.prompts import (
    RANKING_SYSTEM_PROMPT,
    RANKING_USER_PROMPT_TEMPLATE,
    format_articles_for_ranking,
)

logger = logging.getLogger(__name__)

PRIORITY_MAP = {
    "CRITICAL_ACT_NOW": Priority.CRITICAL,
    "IMPORTANT_READ_THIS_WEEK": Priority.IMPORTANT,
    "INTERESTING_QUEUE_FOR_WEEKEND": Priority.INTERESTING,
    "REFERENCE_SAVE_FOR_LATER": Priority.REFERENCE,
}


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
    ) -> list[Article]:
        if not articles:
            return []

        # Split into batches if needed
        all_ranked: list[Article] = []
        for i in range(0, len(articles), self.max_batch_size):
            batch = articles[i : i + self.max_batch_size]
            ranked = self._rank_single_batch(batch, user_interests)
            all_ranked.extend(ranked)
        return all_ranked

    def _rank_single_batch(
        self,
        articles: list[Article],
        user_interests: list[str],
    ) -> list[Article]:
        article_dicts = [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source_name,
                "summary": a.raw_summary[:300],
                "url": a.url,
            }
            for a in articles
        ]

        articles_text = format_articles_for_ranking(article_dicts)
        user_prompt = RANKING_USER_PROMPT_TEMPLATE.format(
            interests=", ".join(user_interests),
            count=len(articles),
            articles_text=articles_text,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=RANKING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            response_text = response.content[0].text  # type: ignore[union-attr]
            rankings = self._parse_rankings(response_text)
        except Exception:
            logger.exception("Claude API call failed, assigning default priority")
            for a in articles:
                a.priority = Priority.REFERENCE
                a.ai_summary = "Ranking unavailable"
            return articles

        # Apply rankings to articles
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

    def _parse_rankings(self, text: str) -> list[dict[str, str]]:
        text = text.strip()
        # Handle markdown code fences
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
