"""Source scanner: discovers new content sources via Claude + web search."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    from newsletter_agent.config import AppConfig
    from newsletter_agent.state.store import StateStore

logger = logging.getLogger(__name__)

SCAN_MODEL = "claude-sonnet-4-6"

SCAN_SYSTEM_PROMPT = """\
You are a resource discovery assistant. Your job is to search the web and \
find high-quality content sources and resources that match the user's \
profile, interests, and learning goals.

You should find ANY type of resource that would be valuable to this person. \
This includes but is not limited to:
- Blogs and websites (look for their RSS/Atom feed URL if one exists)
- Newsletters
- Subreddits
- YouTube channels
- Podcasts
- Forums and communities
- Online courses and tutorials
- Documentation sites
- Tools and software
- Books and reading lists
- Conferences and events
- Social media accounts to follow
- Any other resource type relevant to the user's interests

The user's domain could be anything — technology, cooking, art, finance, \
fitness, music, science, or any other field. Tailor your search entirely \
to what THEY care about based on their profile.

Requirements:
- Do NOT suggest resources the user already has (listed in "Existing resources").
- Focus on quality over quantity — suggest 5-20 resources.
- Prefer resources that are actively maintained and regularly updated.
- Include a mix of resource types, not just one kind.
- Match the depth to the user's skill level.
- Search broadly across the user's interest areas.
- For blogs and websites, search for their RSS/Atom feed URL. Include it \
in the feed_url field if found.

After searching, respond with ONLY a JSON object in this exact format:
{
  "resources": [
    {
      "name": "Resource Name",
      "url": "https://main-page-url",
      "feed_url": null,
      "type": "blog|newsletter|subreddit|youtube|podcast|forum|course|\
tool|community|documentation|book|conference|social|other",
      "description": "What this is and why it's relevant to the user"
    }
  ],
  "summary": "Brief summary of what you found and why these resources \
match the user's profile"
}

Rules for the feed_url field:
- For blogs/websites: set feed_url to the RSS/Atom feed URL if you can \
find one. Set to null if no feed exists.
- For subreddits: set feed_url to null (the agent handles Reddit feeds).
- For everything else: set feed_url to null.

Respond ONLY with the JSON object, no other text."""


def _build_scan_prompt(
    about_me: str,
    interests: list[str],
    existing_resources: list[dict[str, str]],
) -> str:
    parts = []

    if about_me:
        parts.append(f"User profile:\n{about_me}")

    if interests:
        parts.append(f"User's interests: {', '.join(interests)}")

    if existing_resources:
        res_lines = []
        for r in existing_resources:
            res_type = r.get("type", "other")
            name = r.get("name", "")
            url = r.get("url", "")
            res_lines.append(f"  - [{res_type}] {name}: {url}")
        parts.append("Existing resources (do NOT suggest these):\n" + "\n".join(res_lines))

    parts.append(
        "Search the web to find new, high-quality resources this person should know about. "
        "Search broadly — find blogs, YouTube channels, podcasts, communities, courses, "
        "tools, newsletters, and anything else relevant to their profile and interests."
    )

    return "\n\n".join(parts)


class ScanResults:
    def __init__(
        self,
        resources: list[dict[str, str | None]],
        summary: str,
    ):
        self.resources = resources
        self.summary = summary

    @property
    def total(self) -> int:
        return len(self.resources)

    @property
    def is_empty(self) -> bool:
        return self.total == 0


class SourceScanner:
    def __init__(self, config: AppConfig, state: StateStore, about_me: str = ""):
        self.config = config
        self.state = state
        self.about_me = about_me
        self.client = anthropic.Anthropic(api_key=config.llm.api_key)

    def scan(self) -> ScanResults:
        existing = self.state.get_all_resources()
        prompt = _build_scan_prompt(
            about_me=self.about_me,
            interests=self.config.interests,
            existing_resources=existing,
        )

        logger.info("Scanning with %s + web search...", SCAN_MODEL)
        response = self.client.messages.create(
            model=SCAN_MODEL,
            max_tokens=4096,
            system=SCAN_SYSTEM_PROMPT,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 10,
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_response(response)

    def _parse_response(self, response: anthropic.types.Message) -> ScanResults:
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text

        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse scan response as JSON")
            return ScanResults([], "Scan failed to produce valid results.")

        return ScanResults(
            resources=data.get("resources", []),
            summary=data.get("summary", ""),
        )


def apply_scan_results(
    state: StateStore,
    results: ScanResults,
    selected_indices: list[int],
) -> tuple[int, int, int]:
    """Apply selected scan results to the database.

    Resources with feed_url get source_type='rss' (auto-fetched daily).
    Subreddits get source_type='reddit' (auto-fetched daily).
    Everything else gets source_type=None (reference only).

    Returns (feeds_added, subreddits_added, resources_added).
    """
    feeds_added = 0
    subs_added = 0
    resources_added = 0

    for idx in selected_indices:
        res = results.resources[idx]
        res_type = res.get("type", "other")
        feed_url = res.get("feed_url")
        name = res.get("name", "")
        url = res.get("url", "")
        description = res.get("description", "")

        if feed_url:
            result = state.add_resource(
                name=name, url=url, feed_url=feed_url,
                resource_type=res_type, source_type="rss",
                discovered_by="scan", description=description,
            )
            if result is not None:
                feeds_added += 1

        elif res_type == "subreddit":
            sub_name = name if name.startswith("r/") else f"r/{name}"
            sub_url = url or f"https://www.reddit.com/{sub_name}"
            result = state.add_resource(
                name=sub_name, url=sub_url,
                resource_type="subreddit", source_type="reddit",
                discovered_by="scan", description=description,
            )
            if result is not None:
                subs_added += 1

        else:
            result = state.add_resource(
                name=name, url=url,
                resource_type=res_type, source_type=None,
                discovered_by="scan", description=description,
            )
            if result is not None:
                resources_added += 1

    return feeds_added, subs_added, resources_added
