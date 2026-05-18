"""URL merger — combines results from all search layers and deduplicates."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from newsletter_agent.search.models import LayerResult, SearchResult

UTM_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "via", "fbclid", "gclid", "msclkid",
})


def normalize_search_url(url: str) -> str:
    parsed = urlparse(url)

    # Lowercase domain, strip www.
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Strip tracking params
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in params.items() if k.lower() not in UTM_PARAMS}
        query = urlencode(filtered, doseq=True) if filtered else ""
    else:
        query = ""

    # Rebuild without fragment, strip trailing slash from path
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, netloc, path, "", query, ""))


def merge_and_deduplicate(layer_results: list[LayerResult]) -> list[SearchResult]:
    url_map: dict[str, SearchResult] = {}
    url_layers: dict[str, list[str]] = {}

    for layer in layer_results:
        if not layer.success:
            continue
        for result in layer.results:
            norm = normalize_search_url(result.url)
            if norm in url_map:
                # Keep the version with more data
                existing = url_map[norm]
                if result.full_content and not existing.full_content:
                    url_map[norm] = result
                elif result.title and not existing.title:
                    url_map[norm].title = result.title
                elif result.description and not existing.description:
                    url_map[norm].description = result.description
                url_layers[norm].append(layer.layer_name)
            else:
                url_map[norm] = result
                url_layers[norm] = [layer.layer_name]

    # Annotate with cross-layer info
    layer_priority = {"Perplexity Deep": 0, "Exa": 1, "Tavily": 2}
    merged: list[SearchResult] = []
    for norm, result in url_map.items():
        layers = url_layers[norm]
        result.found_by_layers = list(set(layers))
        result.high_confidence = len(set(layers)) >= 3
        merged.append(result)

    # Sort: high confidence first, then by layer count desc, then by layer priority
    merged.sort(key=lambda r: (
        not r.high_confidence,
        -len(r.found_by_layers),
        min(layer_priority.get(lyr, 99) for lyr in r.found_by_layers),
    ))

    return merged
