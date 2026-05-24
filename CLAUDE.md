# Newsletter Agent

## Project Overview
Automated intelligence-gathering system for personalized research.
**Self-bootstrapping**: New users can start with ZERO resources — the Deep Search Engine automatically discovers and populates index pages (RSS feeds, mailing lists, GitHub repos, conference archives) based on topic-focused searches.
Monitors curated sources, runs a multi-layer deep search engine,
uses Claude API for ranking/categorization based on user profile,
delivers prioritized daily digest via Resend email.

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) for article ranking, web source AI fallback, and search query generation
- Deep Search Engine with 3 parallel layers: Tavily, Exa Neural Search, Perplexity Deep Research
- Tavily Search API for broad web article discovery
- Exa Neural Search for semantic/neural article discovery
- Perplexity Deep Research (sonar-deep-research) for deep research synthesis
- DeepSeek V4 Flash for relevance filtering
- OpenAI API for semantic dedup embeddings
- Resend API for email delivery
- Firecrawl API for web page extraction (optional, 1000 free credits/month)
- Jina Reader for free Markdown extraction from web pages
- Click for CLI
- Pydantic for config validation and data models
- httpx for async HTTP, feedparser for RSS, BeautifulSoup for scraping
- python-dotenv for auto-loading .env
- SQLite for state persistence AND resource management

## Project Structure
- `src/newsletter_agent/` — main package (src layout)
- `src/newsletter_agent/sources/` — 3 source types: rss, reddit, web (all extend BaseSource)
- `src/newsletter_agent/ranking/` — Claude API integration for prioritization + DeepSeek filtering
- `src/newsletter_agent/delivery/` — Resend email + HTML templates
- `src/newsletter_agent/state/` — SQLite state persistence + resource DB
- `src/newsletter_agent/search/` — Deep Search Engine: query generation, 4 search layers, URL merger
- `src/newsletter_agent/report.py` — per-run health report (RunReport dataclass)
- `src/newsletter_agent/cost_tracker.py` — per-run cost estimation
- `src/newsletter_agent/utils.py` — URL normalization, semantic dedup
- `src/newsletter_agent/validation.py` — centralized junk detection for articles and resources
- `src/newsletter_agent/scheduling.py` — LaunchAgent/crontab/Task Scheduler scheduling
- `AboutMe.md` — user profile (skills, interests, learning goals)
- `tests/` — mirrors src structure
- `config.yaml` — operational config only (no URLs — those live in the DB)

## Key Commands
```bash
uv run newsletter send                  # full pipeline: fetch + web search + rank + email
uv run newsletter send --dry-run        # preview without sending
uv run newsletter send -m claude-sonnet-4-6  # use Sonnet for ranking
uv run newsletter send -t "Prompt Injection"  # topic-focused digest
uv run newsletter resources             # list all resources in DB
uv run newsletter add-resource          # manually add a resource
uv run newsletter remove-resource <ID>  # remove a resource by DB ID
uv run newsletter sources               # list source status + health
uv run newsletter status                # show state (SQLite backend)
uv run newsletter test-source <id>      # debug one source (rss, reddit, web)
uv run newsletter history               # browse past digests
uv run newsletter history --detail <ID> # view full past digest
uv run newsletter install-schedule      # install daily schedule
uv run newsletter install-schedule --uninstall  # remove schedule
uv run newsletter re-enable <source>    # reset error count for a source
uv run pytest                           # run tests
uv run ruff check src/ tests/           # lint
uv run mypy src/                        # type check
```

## Architecture Rules
- Every source implements BaseSource (sources/base.py)
- Only 3 source types: rss, reddit, web — everything else is a resource in the DB
- Pipeline flow: fetch all → deep search (4 layers) → deduplicate → filter → rank → format → deliver
- No `since` / time filtering — sources fetch everything, dedup handles repeats
- No source-specific logic in pipeline.py
- All HTTP requests use httpx (async)
- State AND resources are SQLite in data/newsletter.db (gitignored)
- No hardcoded URLs in config — all resources (RSS feeds, subreddits, web pages) live in the DB
- Config.yaml is operational settings only (toggles, thresholds)
- Config is validated by Pydantic at load time
- API keys come from .env (auto-loaded via python-dotenv), never config files
- All API clients have hardcoded base_url to prevent localhost redirect
- Sources use `instantiate_source()` in sources/__init__.py for construction
- `RSSSource` and `RedditSource` read their URLs/subreddits from the resources table
- `WebSource` reads URLs from the resources table and uses tiered extraction with auto-pagination
- User profile (AboutMe.md) is injected into ranking prompts for personalization
- Batch API is the default ranking mode (50% cheaper, configurable via `llm.use_batch`)

## Resource Management
- All resources (RSS feeds, subreddits, web pages, etc.) are stored in the `resources` table in SQLite
- Resources can be populated in 2 ways:
  1. **Manually** via `add-resource` command (`discovered_by='user'`)
  2. **Automatically** by Deep Search Engine (`discovered_by='deep_search'`)
- **Auto-discovery workflow**:
  - Deep Search Engine finds URLs during topic-focused searches
  - DeepSeek LLM classifies URLs as "article" (direct content) or "index" (aggregator/landing page)
  - Index pages are routed through deterministic WebSource extraction
  - **Index pages are ONLY added to DB if extraction returns articles** (0-article pages are skipped)
  - This prevents polluting the DB with 403 errors, DNS failures, or empty pages
  - Discovered resources persist for future runs — building a self-improving knowledge base
- Resources with `source_type='rss'` are auto-fetched by the RSS source
- Resources with `source_type='reddit'` are auto-fetched by the Reddit source
- Resources with `source_type='web'` are auto-fetched by the Web source (tiered extraction + pagination)
- Resources with `source_type=NULL` are reference-only (bookmarks)
- `discovered_by` tracks origin: 'user' (manual) or 'deep_search' (auto-discovered)
- Manage via CLI: `newsletter resources`, `newsletter add-resource`, `newsletter remove-resource`

## Self-Bootstrapping for New Users
**New users don't need to manually curate sources.** The system auto-discovers resources via topic-focused searches:

**Example workflow:**
```bash
# Step 1: Empty database (0 resources)
uv run newsletter resources
# → 0 resources

# Step 2: Run topic-focused digest
uv run newsletter send -t "AI Security"

# Step 3: Deep Search Engine discovers 20-30 index pages:
#   - GitHub repos (awesome-llm-security, AI-red-team guides)
#   - Mailing lists (oss-security archives, LLMSEC workshops)
#   - Conference archives (DEF CON AI Village, Black Hat talks)
#   - Research databases (arXiv AI security papers)
#   - Official advisories (CISA AI guidance, OWASP LLM Top 10)

# Step 4: Check auto-discovered resources
uv run newsletter resources
# → 23 new web resources added automatically

# Step 5: Future runs use discovered resources + continue discovering
uv run newsletter send
# → Fetches from 23 known resources + discovers more via search
```

**Smart filtering**: Index pages that fail extraction (403 Forbidden, DNS errors, 0 articles) are **NOT** added to the DB — keeping resources clean and productive.

**Hybrid approach**: Users can start with 3-5 hand-picked sources, then let the Deep Search Engine discover niche domain-specific resources automatically.

## Deep Search Engine
- Replaces single-layer Tavily scanner with 3 parallel search layers
- Claude Sonnet generates 20 targeted queries across 6 categories (CORE, DEPTH, FORMAT, RESEARCHER, EMERGING, OBSCURE)
- Falls back to 5 hardcoded queries if query generation fails
- **Layer 1A: Tavily** — broad web search, configurable depth (basic/advanced)
- **Layer 1B: Exa** — neural/semantic search, auto/keyword mode (keyword for DEPTH queries with site: operators)
- **Layer 2: Perplexity** — sonar-deep-research model, 2 focused research prompts, URL extraction from citations + regex
- All layers run in parallel via ThreadPoolExecutor(max_workers=3)
- Each layer wrapped in `_safe_run()` — individual layer failures don't crash the engine
- **DeepSeek LLM Classification** — after search layers complete:
  - DeepSeek V4 Flash classifies each URL as "article" (direct content) or "index" (aggregator)
  - Based on URL structure, title, and description (domain-agnostic, works for any topic)
  - Batched processing: 50 URLs per API call with 60s timeout
  - Graceful fallback: defaults to "article" if API fails or key missing
- **Index Page Extraction** — index pages routed through WebSource:
  - Uses tiered extraction: JSON API → RSS → Jina → Firecrawl → HTML → AI
  - Auto-pagination follows "next page" links up to `max_pages` depth
  - **Only added to DB if extraction returns articles** (0-article pages skipped)
  - Prevents DB pollution from 403 errors, DNS failures, dead links
- URL merger normalizes URLs (strip www., trailing slash, UTM params), deduplicates, scores by source diversity
- Results flagged `high_confidence=True` when found by 3+ layers
- Sorted by: high confidence first → layer count desc → layer priority (Perplexity > Exa > Tavily)
- Config-driven: each layer has `enabled` toggle and per-layer settings in `config.yaml`
- Direct articles become Articles with `source_id="web_search"`, index pages added to resources DB

## Adding a New Source
1. Create `src/newsletter_agent/sources/my_source.py`
2. Implement BaseSource (name, source_id, fetch method)
3. Register in `sources/__init__.py` SOURCE_REGISTRY
4. Add toggle in config.py SourcesConfig
5. Wire up instantiation in `sources/__init__.py` instantiate_source()
6. Add tests in `tests/sources/test_my_source.py`

## Source IDs
rss, reddit, web (Tavily articles use `web_search` as source_id but it is not a registered source type)

## Environment Variables
- `ANTHROPIC_API_KEY` — required for ranking, web source AI fallback, and search query generation
- `RESEND_API_KEY` — required for email delivery
- `TAVILY_API_KEY` — required for Tavily search layer (layer skipped if not set)
- `EXA_API_KEY` — required for Exa Neural Search layer (layer skipped if not set)
- `PERPLEXITY_API_KEY` — required for Perplexity Deep Research layer (layer skipped if not set)
- `OPENAI_API_KEY` — required for semantic dedup embeddings (skipped if not set)
- `DEEPSEEK_API_KEY` — required for relevance filtering (skipped if not set)
- `FIRECRAWL_API_KEY` — optional, for Firecrawl extraction tier in web source

## Priority Taxonomy
- `CRITICAL - ACT NOW` — urgent, time-sensitive, directly impacts user's work
- `IMPORTANT - READ THIS WEEK` — relevant paper/tool/update, not urgent
- `INTERESTING - QUEUE FOR WEEKEND` — worth reading, not time-sensitive
- `REFERENCE - SAVE FOR LATER` — archive for future use

## Pipeline Stages
1. **Fetch all** — RSS feeds, Reddit subreddits, web pages with auto-pagination (all DB-driven, no time filter)
2. **Deep search** — 3 parallel search layers (Tavily, Exa, Perplexity) using 20 Claude-generated queries across 6 categories
3. **DeepSeek Classification** — Classify search results as "article" (direct) or "index" (aggregator)
4. **Index extraction** — Route index pages through WebSource, add to DB only if articles extracted
5. **Validation** — Centralized junk detection removes badge images, CDN URLs, URL-as-title, and short-title articles before dedup
6. **Deduplication** — URL normalization + title fingerprinting vs DB history, then OpenAI semantic embeddings for cross-source live dedup
7. **Relevance filtering** — DeepSeek V4 Flash index-based filter removes noise (batched, 50/call, fail-open). Topic mode filters strictly to the specified topic.
8. **Ranking** — Claude ranks and summarizes remaining articles (Batch API by default). Topic mode ranks exclusively by topic relevance.
9. **Digest** — HTML email via Resend; cost breakdown and health report are printed to the CLI

## Run Health Report
Every `send` and `test-source` command prints a health report at the end showing:
- Per-source success/failure/skip with article counts
- Per-feed and per-web-page warnings (403s, extraction failures, 0 articles)
- Deep search layer results (per-layer success/failure, result counts, durations)
- DeepSeek filter stats (kept/removed/batch failures)
- Ranking mode and status
- Dedup strategy (semantic vs fallback) and removal count
- Delivery status (sent/failed/skipped)

## Key Features
- **Self-bootstrapping**: New users can start with ZERO resources — Deep Search Engine auto-discovers and adds 20-30 productive index pages (GitHub repos, mailing lists, conference archives) on first topic run
- **Smart resource filtering**: Index pages only added to DB if extraction returns articles — 403 errors, DNS failures, and 0-article pages automatically skipped
- **LLM classification**: DeepSeek V4 Flash classifies search results as "article" (direct content) or "index" (aggregator) — domain-agnostic, works for any topic
- **3 source types**: RSS, Reddit, Web — all DB-driven, no hardcoded sources
- **No time filtering**: Sources fetch everything, dedup handles repeats — safe for infrequent runs
- **Auto-pagination**: Web sources follow "next page" links up to `max_pages` depth (default 3)
- **Topic-focused digests**: `--topic` flag threads through deep search, filter, ranker, and email for single-topic deep dives
- **SQLite state**: WAL mode, auto-migrates from legacy state.json
- **Two-stage dedup**: DB history (URL + title fingerprint) removes previously seen articles, then OpenAI semantic embeddings catch cross-source duplicates in the live batch
- **Deep Search Engine**: 3 parallel search layers (Tavily, Exa, Perplexity Deep Research) with Claude-generated queries, URL merger, and cross-layer confidence scoring
- **LLM-generated search queries**: Claude Sonnet creates 20 targeted queries across 6 categories (CORE, DEPTH, FORMAT, RESEARCHER, EMERGING, OBSCURE)
- **LLM-generated digest titles**: Claude Haiku generates short contextual titles from digest content and user profile
- **Index-based relevance filtering**: DeepSeek V4 Flash returns indices of relevant articles (batched at 50/call, fail-open)
- **Source health**: Auto-disables sources after 3 consecutive failures, 24h retry cooldown
- **Digest history**: Browse past digests with search, date filters, and detail view
- **Batch API**: 50% cheaper ranking via Claude Batch API (default mode)
- **Cross-platform scheduling**: Daily jobs on macOS (launchd), Linux (cron), Windows (Task Scheduler)
- **User profile**: AboutMe.md drives personalized ranking and article search
- **DB-backed resources**: All RSS feeds, subreddits, web pages stored in SQLite
- **Tiered web extraction**: JSON API → RSS autodiscovery → Jina Reader → Firecrawl → HTML → Claude Haiku AI fallback
- **Run health report**: `send` and `test-source` commands print source/feed/API success/failure summary
- **Cost tracking**: Per-run cost estimates (deep search + DeepSeek + Claude + OpenAI) stored with each digest
- **Permanent article history**: `seen_articles` table is never pruned — full read history
- **Auto-load .env**: python-dotenv loads API keys automatically
- **Hardcoded API base URLs**: All API clients (Anthropic, OpenAI, DeepSeek) use explicit base_url
