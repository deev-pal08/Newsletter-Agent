"""Compare deterministic sources vs deep search engine results."""

from __future__ import annotations

import asyncio
import logging
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

from newsletter_agent.config import load_config
from newsletter_agent.report import RunReport
from newsletter_agent.search.engine import DeepSearchEngine
from newsletter_agent.search.merger import normalize_search_url
from newsletter_agent.sources import get_enabled_sources
from newsletter_agent.state.store import StateStore


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config("config.yaml")
    state = StateStore(config.state_dir)
    about_me_path = config.about_me
    about_me = ""
    try:
        with open(about_me_path) as f:
            about_me = f.read()
    except FileNotFoundError:
        pass

    # ── Step 1: Deterministic sources ──
    print("\n" + "=" * 70)
    print("  STEP 1: FETCHING DETERMINISTIC SOURCES (RSS, Reddit, Web)")
    print("=" * 70)

    sources = get_enabled_sources(config, state)
    report = RunReport()

    async def fetch_all():
        tasks = [s.fetch(report=report) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles = []
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                print(f"  [FAIL] {source.name}: {result}")
            else:
                articles.extend(result)
                print(f"  [OK]   {source.name}: {len(result)} articles")
        return articles

    det_articles = asyncio.run(fetch_all())
    det_urls = {normalize_search_url(a.url) for a in det_articles}

    print(f"\n  Total deterministic articles: {len(det_articles)}")
    print(f"  Unique URLs: {len(det_urls)}")

    # ── Step 2: Deep search engine ──
    print("\n" + "=" * 70)
    print("  STEP 2: RUNNING DEEP SEARCH ENGINE")
    print("=" * 70)

    if topic:
        search_topic = topic
    else:
        search_topic = ", ".join(config.interests[:5]) if config.interests else "latest news"
    print(f"  Topic: {search_topic}")
    if topic:
        print("  Mode: TOPIC (focused)")
    else:
        print("  Mode: NORMAL (interests-based)")
    print()

    engine = DeepSearchEngine(
        config=config.search,
        anthropic_api_key=config.llm.api_key,
    )
    result = engine.run(topic=search_topic, about_me=about_me)

    search_urls = {normalize_search_url(r.url) for r in result.merged_results}

    print(f"\n  Total deep search results: {len(result.merged_results)}")
    print(f"  Unique URLs: {len(search_urls)}")
    for lr in result.layer_results:
        status = f"{len(lr.results)} results in {lr.duration_seconds:.1f}s" if lr.success else f"FAILED: {lr.error}"
        print(f"    [{lr.layer_name}] {status}")

    # ── Step 3: Compare ──
    print("\n" + "=" * 70)
    print("  STEP 3: COMPARISON")
    print("=" * 70)

    overlap = det_urls & search_urls
    only_det = det_urls - search_urls
    only_search = search_urls - det_urls

    print(f"\n  Overlap (in both):           {len(overlap)}")
    print(f"  Only in deterministic:       {len(only_det)}")
    print(f"  Only in deep search (NEW):   {len(only_search)}")

    # ── NEW articles from deep search ──
    if only_search:
        print(f"\n  {'─' * 60}")
        print(f"  NEW ARTICLES FROM DEEP SEARCH ({len(only_search)}):")
        print(f"  {'─' * 60}")

        new_results = [
            r for r in result.merged_results
            if normalize_search_url(r.url) in only_search
        ]
        # Group by layer
        by_layer: dict[str, list] = {}
        for r in new_results:
            layer = r.source_layer
            by_layer.setdefault(layer, []).append(r)

        for layer_name, items in sorted(by_layer.items()):
            print(f"\n  [{layer_name.upper()}] ({len(items)} new)")
            for r in items[:15]:
                domain = urlparse(r.url).netloc
                title = r.title[:70] if r.title else "(no title)"
                cat = r.query_category
                print(f"    [{cat}] {title}")
                print(f"           {domain}")
            if len(items) > 15:
                print(f"    ... and {len(items) - 15} more")

    # ── Overlap details ──
    if overlap:
        print(f"\n  {'─' * 60}")
        print(f"  OVERLAP — FOUND BY BOTH ({len(overlap)}):")
        print(f"  {'─' * 60}")
        overlap_results = [
            r for r in result.merged_results
            if normalize_search_url(r.url) in overlap
        ]
        for r in overlap_results[:10]:
            domain = urlparse(r.url).netloc
            title = r.title[:70] if r.title else "(no title)"
            print(f"    {title}")
            print(f"           {domain}")
        if len(overlap_results) > 10:
            print(f"    ... and {len(overlap_results) - 10} more")

    # ── Domain diversity ──
    det_domains = {urlparse(u).netloc for u in det_urls}
    search_domains = {urlparse(u).netloc for u in search_urls}
    new_domains = search_domains - det_domains

    print(f"\n  {'─' * 60}")
    print(f"  DOMAIN DIVERSITY:")
    print(f"  {'─' * 60}")
    print(f"  Deterministic domains: {len(det_domains)}")
    print(f"  Deep search domains:   {len(search_domains)}")
    print(f"  NEW domains from deep search: {len(new_domains)}")
    if new_domains:
        for d in sorted(new_domains)[:20]:
            print(f"    + {d}")
        if len(new_domains) > 20:
            print(f"    ... and {len(new_domains) - 20} more")

    print(f"\n  Cost estimate: ${result.cost_estimate_usd:.2f}")
    print()


if __name__ == "__main__":
    main()
