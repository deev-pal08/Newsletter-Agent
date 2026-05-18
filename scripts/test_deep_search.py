"""Test deep search engine only - show raw URLs returned."""

from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING)

from newsletter_agent.config import load_config
from newsletter_agent.search.engine import DeepSearchEngine


def main() -> None:
    config = load_config("config.yaml")
    about_me = ""
    try:
        with open(config.about_me) as f:
            about_me = f.read()
    except FileNotFoundError:
        pass

    print("=" * 70)
    print("  DEEP SEARCH ENGINE TEST")
    print("=" * 70)

    topic = "AI security"
    print(f"Topic: {topic}\n")

    engine = DeepSearchEngine(
        config=config.search,
        anthropic_api_key=config.llm.api_key,
    )
    result = engine.run(topic=topic, about_me=about_me)

    print(f"\nTotal results: {len(result.merged_results)}")
    print(f"Unique URLs: {result.unique_urls}")
    print(f"Cost: ${result.cost_estimate_usd:.2f}\n")

    for lr in result.layer_results:
        status = f"{len(lr.results)} results" if lr.success else f"FAILED: {lr.error}"
        print(f"  [{lr.layer_name}] {status}")

    print(f"\n{'=' * 70}")
    print("  SAMPLE URLs (first 30):")
    print("=" * 70)

    for i, r in enumerate(result.merged_results[:30], 1):
        print(f"\n{i}. {r.url}")
        print(f"   Title: {r.title or '(no title)'}")
        print(f"   Layer: {r.source_layer} | Category: {r.query_category}")


if __name__ == "__main__":
    main()
