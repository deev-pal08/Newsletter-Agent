"""Utility functions for URL normalization, title similarity, and semantic dedup."""

from __future__ import annotations

import hashlib
import os
import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
}


def normalize_url(url: str, strip_params: set[str] | None = None) -> str:
    """Normalize a URL for dedup: strip tracking params, trailing slash, www, force https."""
    params_to_strip = strip_params or TRACKING_PARAMS
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    scheme = "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in query_params.items() if k.lower() not in params_to_strip}
    query = urlencode(filtered, doseq=True) if filtered else ""

    return urlunparse((scheme, netloc, path, "", query, ""))


def title_fingerprint(title: str) -> str:
    """Create a normalized fingerprint of a title for similarity matching."""
    fp = title.lower()
    fp = re.sub(r"[^\w\s]", "", fp)
    fp = re.sub(r"\s+", " ", fp).strip()
    return fp


def titles_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Check if two titles are similar enough to be considered duplicates."""
    fp_a = title_fingerprint(a)
    fp_b = title_fingerprint(b)
    if not fp_a or not fp_b:
        return False
    return SequenceMatcher(None, fp_a, fp_b).ratio() >= threshold


# ---------------------------------------------------------------------------
# Semantic deduplication via OpenAI embeddings
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()


def _cosine_similarity(a: Any, b: Any) -> float:
    import numpy as np

    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return dot / norm


def compute_embeddings_batch(
    titles: list[str],
    model: str = "text-embedding-3-small",
    state_store: Any = None,
    cache_enabled: bool = True,
) -> list[Any]:
    """Embed all titles in one API call, using SQLite cache where possible."""
    import numpy as np
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    hashes = [_content_hash(t) for t in titles]
    results: list[Any] = [None] * len(titles)
    uncached_indices: list[int] = []

    if cache_enabled and state_store is not None:
        for i, h in enumerate(hashes):
            cached = state_store.get_cached_embedding(h)
            if cached is not None:
                results[i] = np.frombuffer(cached, dtype=np.float32)
            else:
                uncached_indices.append(i)
    else:
        uncached_indices = list(range(len(titles)))

    if uncached_indices:
        client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        uncached_titles = [titles[i] for i in uncached_indices]
        response = client.embeddings.create(
            model=model,
            input=uncached_titles,
        )
        for j, idx in enumerate(uncached_indices):
            vec = np.array(response.data[j].embedding, dtype=np.float32)
            results[idx] = vec
            if cache_enabled and state_store is not None:
                state_store.cache_embedding(
                    hashes[idx], vec.tobytes(),
                )

    return [r for r in results if r is not None]


def find_semantic_duplicates(
    titles: list[str],
    threshold: float = 0.88,
    model: str = "text-embedding-3-small",
    state_store: object | None = None,
    cache_enabled: bool = True,
) -> set[int]:
    """Return indices of titles that are semantic duplicates of an earlier title.

    For each pair (i, j) where i < j, if similarity >= threshold, j is marked
    as a duplicate.
    """
    if len(titles) < 2:
        return set()

    embeddings = compute_embeddings_batch(
        titles, model=model, state_store=state_store, cache_enabled=cache_enabled,
    )

    duplicates: set[int] = set()
    for i in range(len(embeddings)):
        if i in duplicates:
            continue
        for j in range(i + 1, len(embeddings)):
            if j in duplicates:
                continue
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                duplicates.add(j)

    return duplicates
