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

Below is a numbered list of articles. Return ONLY the indices (0-based) of \
articles that are relevant to the user's interests. Exclude noise like job \
postings, generic listicles, off-topic content, and duplicates.

Return ONLY a JSON array of integer indices. No explanation. No markdown.
Example: [0, 2, 5, 7]

Articles:
{articles_json}"""

TOPIC_FILTER_PROMPT_TEMPLATE = """\
You are a strict topic filter for a focused newsletter digest.

The user wants ONLY articles about: "{topic}"

Below is a numbered list of articles. Return ONLY the indices (0-based) of \
articles that are directly related to "{topic}". Be strict — tangentially \
related or off-topic articles must NOT be included.

Return ONLY a JSON array of integer indices. No explanation. No markdown.
Example: [0, 2, 5, 7]

Articles:
{articles_json}"""

BATCH_SIZE = 50


def _filter_batch(
    client: OpenAI,
    articles: list[Article],
    interests: list[str],
    about_me: str,
    model: str,
    topic: str | None = None,
) -> set[int]:
    """Returns set of 0-based indices of articles to KEEP."""
    articles_data = [
        {
            "idx": i,
            "title": a.title,
            "source": a.source_name,
            "summary": a.raw_summary[:200] if a.raw_summary else "",
        }
        for i, a in enumerate(articles)
    ]
    articles_json = json.dumps(articles_data, indent=None)

    if topic:
        prompt = TOPIC_FILTER_PROMPT_TEMPLATE.format(
            topic=topic,
            articles_json=articles_json,
        )
    else:
        prompt = FILTER_PROMPT_TEMPLATE.format(
            about_me=about_me or "Not provided",
            interests=", ".join(interests) if interests else "general",
            articles_json=articles_json,
        )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
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

    indices: list[int] = json.loads(text)
    valid = {i for i in indices if 0 <= i < len(articles)}

    if len(valid) != len(indices):
        logger.warning(
            "Filter returned %d indices, %d valid (out of %d articles)",
            len(indices), len(valid), len(articles),
        )

    return valid


def filter_articles(
    articles: list[Article],
    interests: list[str],
    about_me: str = "",
    model: str = "deepseek-v4-flash",
    fail_open: bool = True,
    report: RunReport | None = None,
    topic: str | None = None,
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
            keep_indices = _filter_batch(client, batch, interests, about_me, model, topic=topic)
            filtered.extend(a for j, a in enumerate(batch) if j in keep_indices)
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
