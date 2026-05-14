"""Utility functions for URL normalization and title similarity."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
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
