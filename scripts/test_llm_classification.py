"""Test complete deep search → classification → extraction → DB flow."""

from __future__ import annotations

import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

from newsletter_agent.config import load_config
from newsletter_agent.search.engine import DeepSearchEngine
from newsletter_agent.search.classifier import classify_search_results
from newsletter_agent.sources.web import WebSource
from newsletter_agent.state.store import StateStore


async def extract_from_index_pages(index_results, config, state):
    """Mirror pipeline._extract_from_index_pages logic."""
    from newsletter_agent.sources.web import WebSource

    all_extracted = []
    new_resources = 0
    resources_before = state.resource_count()

    for r in index_results[:3]:  # Test first 3 only
        url = r.url
        name = r.title or url.split("/")[-1] or url
        print(f"\n  Processing index page: {url[:70]}")

        # Extract articles first
        try:
            web_source = WebSource(
                pages={name[:200]: url},
                api_key=config.llm.api_key,
                jina_enabled=config.extraction.jina_enabled,
                firecrawl_enabled=config.extraction.firecrawl_enabled,
                haiku_fallback_enabled=config.extraction.haiku_fallback_enabled,
                max_pages=config.extraction.max_pages,
            )
            articles = await web_source.fetch()
            print(f"    → Extracted {len(articles)} articles via WebSource")

            # Only add to DB if extraction returned articles AND not already present
            if len(articles) > 0 and not state.resource_exists(url):
                resource_id = state.add_resource(
                    name=name[:200],
                    url=url,
                    source_type="web",
                    discovered_by="deep_search",
                    description=f"Index page from deep search ({r.source_layer})",
                )
                if resource_id is not None:
                    new_resources += 1
                    print(f"    → Added to DB (ID: {resource_id}): {name[:60]} ({len(articles)} articles)")
            elif state.resource_exists(url):
                print(f"    → Already in DB, skipping")
            elif len(articles) == 0:
                print(f"    → Skipped (0 articles extracted)")

            all_extracted.extend(articles)
            if articles:
                for a in articles[:3]:
                    print(f"       - {a.title[:65]}")
                if len(articles) > 3:
                    print(f"       ... and {len(articles) - 3} more")
        except Exception as e:
            print(f"    → Extraction FAILED: {e}")
            print(f"    → Skipped adding to DB (extraction failed)")

    resources_after = state.resource_count()

    return all_extracted, new_resources, resources_before, resources_after


def main() -> None:
    config = load_config("config.yaml")
    state = StateStore(config.state_dir)
    about_me = ""
    try:
        with open(config.about_me) as f:
            about_me = f.read()
    except FileNotFoundError:
        pass

    print("=" * 70)
    print("  COMPLETE FLOW TEST: Deep Search → Classification → Extraction → DB")
    print("=" * 70)

    # Test with a generic topic (not security-specific)
    topic = "renewable energy startups"
    print(f"Topic: {topic}")
    print(f"(Testing generic classification - not domain-specific)\n")

    # Check if DeepSeek API key is set
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if not deepseek_key:
        print("⚠️  WARNING: DEEPSEEK_API_KEY not set")
        print("   Classification will fall back to 'article' for all results")
        print("   Set DEEPSEEK_API_KEY to test LLM classification\n")

    # ── STEP 1: Deep Search ──
    print("─" * 70)
    print("STEP 1: DEEP SEARCH ENGINE")
    print("─" * 70)

    engine = DeepSearchEngine(
        config=config.search,
        anthropic_api_key=config.llm.api_key,
    )
    result = engine.run(topic=topic, about_me=about_me)

    print(f"\nDeep search complete:")
    print(f"  Total results: {len(result.merged_results)}")
    print(f"  Unique URLs: {result.unique_urls}")
    print(f"  Cost: ${result.cost_estimate_usd:.2f}")
    for lr in result.layer_results:
        if lr.success:
            print(f"    [{lr.layer_name}] {len(lr.results)} results")

    # ── STEP 2: DeepSeek Classification ──
    print(f"\n{'─' * 70}")
    print("STEP 2: DEEPSEEK LLM CLASSIFICATION")
    print("─" * 70)

    valid_results = [r for r in result.merged_results if r.url]
    print(f"\nClassifying {len(valid_results)} URLs via DeepSeek Chat API...")

    classifications = classify_search_results(valid_results, api_key=deepseek_key)

    # Split based on classifications
    individual_results = []
    index_results = []
    for r in valid_results:
        classification = classifications.get(r.url, "article")
        if classification == "index":
            index_results.append(r)
        else:
            individual_results.append(r)

    print(f"\nClassification complete:")
    print(f"  Articles (direct): {len(individual_results)}")
    print(f"  Index pages (extract): {len(index_results)}")
    print(f"  Cost: ~$0.01")

    if index_results:
        print(f"\nIndex pages identified:")
        for idx in index_results[:10]:
            print(f"  • {idx.url[:65]}")
            print(f"    {idx.title or '(no title)'}")
        if len(index_results) > 10:
            print(f"  ... and {len(index_results) - 10} more")

    # ── STEP 3: Deterministic Extraction ──
    print(f"\n{'─' * 70}")
    print("STEP 3: DETERMINISTIC EXTRACTION (WebSource)")
    print("─" * 70)

    if not index_results:
        print("\nNo index pages found - skipping extraction")
    else:
        print(f"\nExtracting from {min(3, len(index_results))} index pages:")
        print("(Testing first 3 only)")

        extracted, new_resources, res_before, res_after = asyncio.run(
            extract_from_index_pages(index_results, config, state)
        )

        print(f"\n{'─' * 70}")
        print("STEP 4: RESOURCE DB UPDATE")
        print("─" * 70)
        print(f"\nResources before: {res_before}")
        print(f"Resources after:  {res_after}")
        print(f"New resources added: {new_resources}")

        print(f"\nExtraction summary:")
        print(f"  Index pages processed: {min(3, len(index_results))}")
        print(f"  Articles extracted: {len(extracted)}")
        print(f"  New resources in DB: {new_resources}")

        if extracted:
            print(f"\nSample extracted articles:")
            for a in extracted[:5]:
                print(f"  • {a.title[:65]}")
            if len(extracted) > 5:
                print(f"  ... and {len(extracted) - 5} more")

    # ── FINAL SUMMARY ──
    print(f"\n{'═' * 70}")
    print("FINAL SUMMARY")
    print("═" * 70)
    print(f"✓ Deep search: {len(valid_results)} URLs found")
    print(f"✓ Classification: {len(individual_results)} articles, {len(index_results)} index pages")
    if index_results:
        print(f"✓ Extraction: {len(extracted)} articles from {min(3, len(index_results))} index pages")
        print(f"✓ Resource DB: {new_resources} new resources added")
    print(f"\nTotal cost estimate: ~${result.cost_estimate_usd + 0.01:.2f}")
    print()


if __name__ == "__main__":
    main()
