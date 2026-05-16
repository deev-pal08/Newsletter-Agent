"""DeepSeek-based relevance filter — removes noise before expensive ranking."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from openai import OpenAI

from newsletter_agent.models import Article

if TYPE_CHECKING:
    from newsletter_agent.report import RunReport

logger = logging.getLogger(__name__)

FILTER_PROMPT_TEMPLATE = """\
You are a relevance filter for a personalized newsletter.

User profile:
{about_me}

User's focus areas: {interests}

Below is a JSON array of articles. For each article, return true if it is \
relevant to the user's interests, false if it is noise (job postings, \
generic listicles, off-topic content, duplicates of major news already \
widely covered).

Return ONLY a JSON array of booleans in the same order as the input. \
No explanation. No markdown. Example: [true, false, true, true, false]

Articles:
{articles_json}"""

BATCH_SIZE = 100


def _filter_batch(
    client: OpenAI,
    articles: list[Article],
    interests: list[str],
    about_me: str,
    model: str,
) -> list[bool]:
    articles_data = [
        {
            "title": a.title,
            "source": a.source_name,
            "summary": a.raw_summary[:200] if a.raw_summary else "",
        }
        for a in articles
    ]
    articles_json = json.dumps(articles_data, indent=None)

    prompt = FILTER_PROMPT_TEMPLATE.format(
        about_me=about_me or "Not provided",
        interests=", ".join(interests) if interests else "general",
        articles_json=articles_json,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=8192,
        temperature=0,
    )
    text = response.choices[0].message.content or ""
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    verdicts: list[bool] = json.loads(text)

    if len(verdicts) != len(articles):
        diff = abs(len(verdicts) - len(articles))
        if diff <= 2:
            logger.warning(
                "Filter returned %d verdicts for %d articles, adjusting",
                len(verdicts), len(articles),
            )
            if len(verdicts) < len(articles):
                verdicts.extend([True] * (len(articles) - len(verdicts)))
            else:
                verdicts = verdicts[: len(articles)]
        else:
            raise ValueError(
                f"Filter returned {len(verdicts)} verdicts for {len(articles)} articles",
            )

    return verdicts


def filter_articles(
    articles: list[Article],
    interests: list[str],
    about_me: str = "",
    model: str = "deepseek-chat",
    fail_open: bool = True,
    report: RunReport | None = None,
) -> list[Article]:
    """Filter articles for relevance using DeepSeek.

    Processes articles in batches to avoid response truncation.
    Returns only articles deemed relevant. If the API call fails and
    fail_open is True, returns all articles unchanged.
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.info("DEEPSEEK_API_KEY not set — skipping relevance filter")
        if report is not None:
            report.filter_skipped = "DEEPSEEK_API_KEY not set"
        return articles

    if not articles:
        return articles

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
    )

    filtered: list[Article] = []
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        try:
            verdicts = _filter_batch(client, batch, interests, about_me, model)
            filtered.extend(a for a, keep in zip(batch, verdicts, strict=True) if keep)
        except Exception:
            logger.warning(
                "Relevance filter failed for batch %d-%d",
                i, i + len(batch), exc_info=True,
            )
            if report is not None:
                report.filter_fallbacks.append(
                    f"Batch {i}-{i + len(batch)} failed, kept all",
                )
            if fail_open:
                filtered.extend(batch)
            else:
                raise

    removed = len(articles) - len(filtered)
    logger.info("Relevance filter: %d kept, %d removed", len(filtered), removed)
    if report is not None:
        report.filter_kept = len(filtered)
        report.filter_removed = removed
    return filtered
