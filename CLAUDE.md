# Newsletter Agent

## Project Overview
Automated intelligence-gathering system for personalized research.
Monitors curated sources, searches the web for fresh articles via Tavily,
uses Claude API for ranking/categorization based on user profile,
delivers prioritized daily digest via Resend email.

## Tech Stack
- Python 3.12, managed with uv
- Claude API (anthropic SDK) for article ranking and web source AI fallback
- Tavily Search API for web article discovery
- DeepSeek API for pre-ranking relevance filtering (batched, 100 articles/call)
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
- `src/newsletter_agent/scanner.py` — web article discovery via Tavily Search
- `src/newsletter_agent/report.py` — per-run health report (RunReport dataclass)
- `src/newsletter_agent/cost_tracker.py` — per-run cost estimation
- `src/newsletter_agent/utils.py` — URL normalization, semantic dedup
- `src/newsletter_agent/scheduling.py` — LaunchAgent/crontab/Task Scheduler scheduling
- `AboutMe.md` — user profile (skills, interests, learning goals)
- `tests/` — mirrors src structure
- `config.yaml` — operational config only (no URLs — those live in the DB)

## Key Commands
```bash
uv run newsletter send                  # full pipeline: fetch + web search + rank + email
uv run newsletter send --dry-run        # preview without sending
uv run newsletter send -m claude-sonnet-4-6  # use Sonnet for ranking
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
- Pipeline flow: deterministic fetch → Tavily web search → deduplicate → filter → rank → format → deliver
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
- `WebSource` reads URLs from the resources table and uses tiered extraction (JSON → RSS → Jina → Firecrawl → HTML → AI fallback)
- User profile (AboutMe.md) is injected into ranking prompts for personalization
- Batch API is the default ranking mode (50% cheaper, configurable via `llm.use_batch`)

## Resource Management
- All resources (RSS feeds, subreddits, web pages, etc.) are stored in the `resources` table in SQLite
- Resources are hardcoded sources of data — users populate them manually via `add-resource`
- Resources with `source_type='rss'` are auto-fetched daily by the RSS source
- Resources with `source_type='reddit'` are auto-fetched daily by the Reddit source
- Resources with `source_type='web'` are auto-fetched daily by the Web source (tiered: JSON API → RSS → Jina → Firecrawl → HTML → AI fallback)
- Resources with `source_type=NULL` are reference-only (bookmarks)
- `discovered_by` tracks origin: 'user'
- Manage via CLI: `newsletter resources`, `newsletter add-resource`, `newsletter remove-resource`

## Web Article Search (Tavily)
- Every `send` run searches the web for fresh articles via Tavily Search API
- Searches are driven by the user's AboutMe.md profile and interests
- Finds actual data: articles, CVEs, research papers, talks, reports — not resources
- Results are combined with deterministic source fetch before dedup/ranking
- Gracefully skipped if `TAVILY_API_KEY` is not set

## Adding a New Source
1. Create `src/newsletter_agent/sources/my_source.py`
2. Implement BaseSource (name, source_id, fetch method)
3. Register in `sources/__init__.py` SOURCE_REGISTRY
4. Add toggle in config.py SourcesConfig
5. Wire up instantiation in `sources/__init__.py` instantiate_source()
6. Add tests in `tests/sources/test_my_source.py`

## Source IDs
rss, reddit, web

## Environment Variables
- `ANTHROPIC_API_KEY` — required for ranking and web source AI fallback
- `RESEND_API_KEY` — required for email delivery
- `TAVILY_API_KEY` — required for web article search (skipped if not set)
- `OPENAI_API_KEY` — required for semantic dedup embeddings (skipped if not set)
- `DEEPSEEK_API_KEY` — required for relevance filtering (skipped if not set)
- `FIRECRAWL_API_KEY` — optional, for Firecrawl extraction tier in web source

## Priority Taxonomy
- `CRITICAL - ACT NOW` — urgent, time-sensitive, directly impacts user's work
- `IMPORTANT - READ THIS WEEK` — relevant paper/tool/update, not urgent
- `INTERESTING - QUEUE FOR WEEKEND` — worth reading, not time-sensitive
- `REFERENCE - SAVE FOR LATER` — archive for future use

## Pipeline Stages
1. **Deterministic fetch** — RSS feeds, Reddit subreddits, web pages (all DB-driven)
2. **Web article search** — Tavily searches for fresh articles matching profile/interests
3. **Deduplication** — URL normalization + title fingerprinting vs DB history, then OpenAI semantic embeddings for cross-source live dedup
4. **Relevance filtering** — DeepSeek binary filter removes noise (batched, 100/call, fail-open)
5. **Ranking** — Claude ranks and summarizes remaining articles (Batch API by default)
6. **Digest** — HTML email via Resend with cost breakdown and health report

## Run Health Report
Every `send` and `test-source` command prints a health report at the end showing:
- Per-source success/failure/skip with article counts
- Per-feed and per-web-page warnings (403s, extraction failures, 0 articles)
- Tavily discovery query results
- DeepSeek filter stats (kept/removed/batch failures)
- Ranking mode and status
- Dedup strategy (semantic vs fallback) and removal count
- Delivery status (sent/failed/skipped)

## Key Features
- **3 source types**: RSS, Reddit, Web — all DB-driven, no hardcoded sources
- **SQLite state**: WAL mode, auto-migrates from legacy state.json
- **Two-stage dedup**: DB history (URL + title fingerprint) removes previously seen articles, then OpenAI semantic embeddings catch cross-source duplicates in the live batch
- **Source health**: Auto-disables sources after 3 consecutive failures, 24h retry cooldown
- **Digest history**: Browse past digests with search, date filters, and detail view
- **Batch API**: 50% cheaper ranking via Claude Batch API (default mode)
- **Cross-platform scheduling**: Daily jobs on macOS (launchd), Linux (cron), Windows (Task Scheduler)
- **User profile**: AboutMe.md drives personalized ranking and article search
- **DB-backed resources**: All RSS feeds, subreddits, web pages stored in SQLite
- **Web source (AI-assisted)**: Tiered extraction: JSON → RSS → Jina → Firecrawl → HTML → Claude Haiku AI fallback
- **Run health report**: Every command prints source/feed/API success/failure summary
- **Cost tracking**: Per-run cost estimates stored with each digest
- **Permanent article history**: `seen_articles` table is never pruned — full read history
- **Auto-load .env**: python-dotenv loads API keys automatically
- **Hardcoded API base URLs**: All API clients (Anthropic, OpenAI, DeepSeek) use explicit base_url
