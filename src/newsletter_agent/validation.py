"""Validation rules for articles and resources — prevents garbage from entering the DB."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from newsletter_agent.models import Article

_JUNK_URL_RE = re.compile(
    r"img\.shields\.io"
    r"|camo\.githubusercontent\.com"
    r"|badge\."
    r"|cdn-cgi/image"
    r"|\.(?:png|jpg|jpeg|gif|svg|ico|webp)(?:\?|$)"
    r"|github\.com/[^/]+/[^/]+/"
    r"(?:stargazers|watchers|network|graphs|issues$|pulls$)"
    r"|twitter\.com/intent/"
    r"|linkedin\.com/sharing",
    re.IGNORECASE,
)

_JUNK_RESOURCE_URL_RE = re.compile(
    r"/blob/"
    r"|/tree/main$"
    r"|github\.com/topics/"
    r"|\.(?:png|jpg|jpeg|gif|svg|ico|webp)(?:\?|$)"
    r"|img\.shields\.io"
    r"|camo\.githubusercontent\.com",
    re.IGNORECASE,
)


def is_junk_article(article: Article) -> bool:
    url = article.url
    title = article.title

    if not url or not url.startswith("http"):
        return True
    if not title or len(title) < 5:
        return True
    if title.startswith("http://") or title.startswith("https://"):
        return True
    return is_junk_article_url(url)


def is_junk_article_url(url: str) -> bool:
    return bool(_JUNK_URL_RE.search(url))


def is_junk_resource_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return True
    return bool(_JUNK_RESOURCE_URL_RE.search(url))
