"""Classify deep search results as individual articles vs index pages using LLM."""

from __future__ import annotations

import json
import logging
import os

import httpx

from newsletter_agent.search.models import SearchResult

logger = logging.getLogger(__name__)

DEEPSEEK_CLASSIFICATION_PROMPT = """You are analyzing a list of web URLs discovered during a search.

For each URL, classify whether it serves:
- "article": Individual content (blog post, research paper, video, GitHub repo,
  discussion thread, product page, etc.)
- "index": Aggregator/landing page (blog homepage, category listing, topic index,
  RSS feed, documentation hub, etc.)

Base your classification on the URL structure, title, and description provided.
Do not make assumptions about the domain or topic - classify based purely on whether
the URL serves individual content or aggregates multiple pieces of content.

URLs to classify:
{urls_block}

Return your response as valid JSON in this exact format:
{{
  "classifications": [
    {{"url": "https://example.com/page1", "type": "article"}},
    {{"url": "https://example.com/page2", "type": "index"}}
  ]
}}

Return ONLY the JSON, no other text."""


def classify_search_results(
    results: list[SearchResult],
    api_key: str | None = None,
    batch_size: int = 50,
) -> dict[str, str]:
    """
    Classify search results as 'article' or 'index' using DeepSeek V4 Flash.

    Args:
        results: List of SearchResult objects to classify
        api_key: DeepSeek API key (defaults to DEEPSEEK_API_KEY env var)
        batch_size: Number of URLs to classify per API call (default: 50)

    Returns:
        Dictionary mapping URL to classification: {"https://...": "article"}

    Raises:
        ValueError: If API key is not provided and DEEPSEEK_API_KEY env var is not set
        httpx.HTTPError: If the API request fails
    """
    if not results:
        return {}

    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        logger.warning(
            "DEEPSEEK_API_KEY not set — falling back to 'article' for all results"
        )
        return {r.url: "article" for r in results}

    # Process in batches to avoid timeout on large result sets
    all_classifications = {}
    for i in range(0, len(results), batch_size):
        batch = results[i:i + batch_size]
        batch_classifications = _classify_batch(batch, api_key)
        all_classifications.update(batch_classifications)

    logger.info(
        "DeepSeek classified %d URLs: %d articles, %d index pages",
        len(results),
        sum(1 for v in all_classifications.values() if v == "article"),
        sum(1 for v in all_classifications.values() if v == "index"),
    )

    return all_classifications


def _classify_batch(
    results: list[SearchResult],
    api_key: str,
) -> dict[str, str]:
    """Classify a single batch of results."""
    # Build URLs block for prompt
    urls_block = ""
    for idx, r in enumerate(results, 1):
        urls_block += f"{idx}. {r.url}\n"
        urls_block += f"   Title: {r.title or '(no title)'}\n"
        desc = r.description[:200] if r.description else "(no description)"
        urls_block += f"   Description: {desc}\n\n"

    prompt = DEEPSEEK_CLASSIFICATION_PROMPT.format(urls_block=urls_block)

    try:
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
            },
            timeout=60.0,  # Increased timeout for larger batches
        )
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()

        # Parse JSON response
        parsed = json.loads(content)
        classifications = parsed.get("classifications", [])

        # Build result dict
        result_map = {}
        for item in classifications:
            url = item.get("url")
            classification_type = item.get("type", "article")
            if url:
                result_map[url] = classification_type

        return result_map

    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
        logger.warning(
            "DeepSeek classification failed for batch: %s — falling back to 'article'",
            e,
        )
        return {r.url: "article" for r in results}
