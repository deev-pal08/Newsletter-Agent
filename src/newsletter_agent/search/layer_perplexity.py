"""Layer 2 — Perplexity Sonar Deep Research."""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai

from newsletter_agent.search.models import LayerResult, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an intelligence research agent. "
    "Your job is to find URLs. Always include full URLs "
    "for every source you mention. Be exhaustive."
)


def _build_prompts(
    topic: str, about_me: str, queries: list[SearchQuery],
    domain_context: str = "",
) -> list[str]:
    about_short = about_me[:500] if about_me else "Not provided"
    domain_section = ""
    if domain_context:
        domain_section = (
            f"\n\nDomain-specific priorities:\n{domain_context}\n"
            f"Prioritize sources and results matching these domain priorities.\n"
        )

    prompt_overview = (
        f"You are a research agent for an intelligence newsletter.\n\n"
        f"User profile summary:\n{about_short}\n\n"
        f"Task: Find every significant resource published in the last 7 days "
        f"related to: {topic}\n\n"
        f"Search exhaustively across:\n"
        f"- Official announcements, advisories, and disclosures\n"
        f"- Expert and practitioner blogs and writeups\n"
        f"- Academic papers and conference presentations\n"
        f"- Industry reports and analysis\n"
        f"- GitHub repositories and project updates\n"
        f"- Government and regulatory publications\n"
        f"- Mailing lists, forums, and community discussions\n\n"
        f"For each resource found, provide the direct URL and a one-sentence summary.\n"
        f"Format your response as a list of sources with URLs clearly visible.\n"
        f"Include EVERY source you find, even obscure ones. Quantity and breadth matter."
        f"{domain_section}"
    )

    prompt_deep_dive = (
        f"Find all in-depth technical writeups, detailed analyses, working code, "
        f"and hands-on tutorials related to {topic} from the last 14 days. "
        f"Include GitHub repositories, blog posts with implementation details, "
        f"and practitioner threads with technical depth. "
        f"{domain_section}"
        f"List every URL you find."
    )

    return [prompt_overview, prompt_deep_dive]


def _extract_urls_from_response(
    response: object, prompt_text: str,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()

    # Extract from citations field if present
    citations: list[str] = getattr(response, "citations", []) or []
    for url in citations:
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            results.append(SearchResult(
                url=url,
                title="",
                description="Found via Perplexity Deep Research",
                source_layer="perplexity",
                source_query=prompt_text[:100],
                query_category="CORE",
            ))

    # Extract from response text via regex
    text = ""
    if hasattr(response, "choices") and response.choices:
        msg = response.choices[0].message
        text = getattr(msg, "content", "") or ""

    for match in re.finditer(r'https?://[^\s<>\"\'\)\]]+', text):
        url = match.group(0).rstrip(".,;:)")
        if url not in seen:
            seen.add(url)
            # Use surrounding text as description
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 100)
            context = text[start:end].strip()
            results.append(SearchResult(
                url=url,
                title="",
                description=context[:300],
                source_layer="perplexity",
                source_query=prompt_text[:100],
                query_category="CORE",
            ))

    return results


class PerplexityDeepResearchLayer:
    def __init__(
        self,
        api_key: str,
        model: str = "sonar-deep-research",
        prompts_to_run: int = 2,
        max_concurrent: int = 2,
    ):
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
        )
        self._model = model
        self._prompts_to_run = prompts_to_run
        self._max_concurrent = max_concurrent

    def search(
        self,
        queries: list[SearchQuery],
        topic: str,
        about_me: str,
        domain_context: str = "",
    ) -> LayerResult:
        start = time.monotonic()
        prompts = _build_prompts(
            topic, about_me, queries, domain_context,
        )[:self._prompts_to_run]
        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        def _run_prompt(prompt: str) -> list[SearchResult]:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                return _extract_urls_from_response(response, prompt)
            except Exception:
                logger.warning("Perplexity prompt failed", exc_info=True)
                return []

        with ThreadPoolExecutor(max_workers=self._max_concurrent) as executor:
            futures = {executor.submit(_run_prompt, p): p for p in prompts}
            for future in as_completed(futures):
                for result in future.result():
                    if result.url not in seen_urls:
                        seen_urls.add(result.url)
                        all_results.append(result)

        duration = time.monotonic() - start
        logger.info("Perplexity: %d results in %.1fs", len(all_results), duration)
        return LayerResult(
            layer_name="Perplexity Deep",
            results=all_results,
            query_count=len(prompts),
            success=True,
            duration_seconds=duration,
        )
