# Newsletter Agent

Personalized research intelligence agent. Monitors curated sources, discovers fresh articles via LLM-driven web search, uses Claude to rank signal from noise, and delivers a prioritized digest via email.

## What It Does

1. **Profiles** you via `AboutMe.md` — your skills, experience, and learning goals
2. **Fetches** from 3 DB-driven source types: RSS feeds, Reddit subreddits, and web pages (with AI-assisted extraction and auto-pagination)
3. **Searches** the web via Tavily using LLM-generated queries tailored to your profile and interests
4. **Deduplicates** in two stages: DB history check (URL + title fingerprint), then OpenAI semantic embeddings for cross-source live dedup
5. **Filters** noise via DeepSeek V4 Flash relevance filter (batched, fail-open)
6. **Ranks** using Claude AI into four priority levels: Critical, Important, Interesting, Reference — personalized to your profile
7. **Delivers** a formatted HTML email via Resend with cost breakdown and health report
8. **Reports** per-run health: source/feed/API success and failure summary after every command

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- [Anthropic API key](https://console.anthropic.com/) for article ranking
- [Resend API key](https://resend.com/) for email delivery (free tier: 100 emails/day)

## Quick Start

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the repo
git clone https://github.com/deev-pal08/Newsletter-Agent.git
cd Newsletter-Agent

# 3. Install dependencies
uv sync

# 4. Set up your profile
cp AboutMe.example.md AboutMe.md
# Edit AboutMe.md — describe your skills, experience, and learning goals

# 5. Set up your config
cp config.example.yaml config.yaml
# Edit config.yaml — add your email under email.to_addresses,
# customize interests, toggle source types on/off

# 6. Set up API keys
cp .env.example .env
# Edit .env — paste your API keys (auto-loaded via python-dotenv)

# 7. Add your sources (the DB starts empty)
uv run newsletter add-resource --name "Hacker News" \
  --url "https://news.ycombinator.com" \
  --feed-url "https://hnrss.org/frontpage" \
  --type blog
uv run newsletter add-resource --name "TechCrunch" \
  --url "https://techcrunch.com" \
  --feed-url "https://techcrunch.com/feed/" \
  --type blog

# 8. Test a source
uv run newsletter test-source rss

# 9. Preview a full ranked digest (requires Anthropic key)
uv run newsletter send --dry-run

# 10. Send for real (requires both keys)
uv run newsletter send

# 11. (Optional) Install daily schedule
uv run newsletter install-schedule --time 08:00
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

- **about_me**: Path to your `AboutMe.md` profile (default: `AboutMe.md`)
- **interests**: Your research focus areas (used by Claude for ranking)
- **sources**: Toggle source types on/off (rss, reddit, web)
- **llm.model**: `claude-haiku-4-5` (cheap) or `claude-sonnet-4-6` (better)
- **llm.use_batch**: Use Batch API for 50% cheaper ranking (default: true)
- **discovery**: Tavily query count, domain include/exclude lists, search depth
- **extraction**: Jina/Firecrawl toggles, `max_pages` for auto-pagination depth
- **filtering**: DeepSeek V4 Flash relevance filter toggle
- **email**: Resend delivery settings
- **dedup**: Semantic dedup threshold and embedding model
- **health**: Auto-disable failing sources, retry cooldown

RSS feeds, subreddits, and web pages are managed in the SQLite database — use the CLI commands below to add, remove, and list them.

## Commands

| Command | Description |
|---------|-------------|
| `newsletter send` | Full pipeline: fetch, search, dedup, filter, rank, email |
| `newsletter send --dry-run` | Generate HTML without sending |
| `newsletter send -m claude-sonnet-4-6` | Use a specific model for ranking |
| `newsletter resources` | List all resources in the database |
| `newsletter add-resource` | Add a resource to the database |
| `newsletter remove-resource <ID>` | Remove a resource from the database |
| `newsletter test-source <id>` | Debug a single source (rss, reddit, web) |
| `newsletter sources` | Show source status and health |
| `newsletter status` | Show system state (SQLite backend) |
| `newsletter history` | Browse past digests |
| `newsletter history --detail <ID>` | View a specific past digest |
| `newsletter install-schedule` | Install daily schedule |
| `newsletter install-schedule --uninstall` | Remove installed schedule |
| `newsletter re-enable <source>` | Reset error count for a source |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API for ranking and web source AI fallback |
| `RESEND_API_KEY` | Yes (for email) | Resend API for delivery |
| `TAVILY_API_KEY` | Optional | Tavily Search for web article discovery |
| `OPENAI_API_KEY` | Optional | OpenAI embeddings for semantic dedup |
| `DEEPSEEK_API_KEY` | Optional | DeepSeek V4 Flash for relevance filter and search query generation |
| `FIRECRAWL_API_KEY` | Optional | Firecrawl for web page extraction (1000 free credits/month) |

All keys are stored in `.env` (gitignored) and auto-loaded via python-dotenv. Optional services degrade gracefully when their keys are not set.

## User Profile (AboutMe.md)

The `AboutMe.md` file tells the agent who you are. Copy the template and fill it in:

```bash
cp AboutMe.example.md AboutMe.md
```

Sections:
- **Who I Am** — your role and background
- **Skills & Expertise** — what you're already good at (avoids overly basic content)
- **Experience** — relevant professional/educational background
- **Learning Goals** — what you want to learn (the agent prioritizes these)
- **Topics I Follow** — specific subjects to stay updated on
- **What I'm Building** — current projects (surfaces relevant tools)

The profile is injected into Claude's ranking prompts and used by DeepSeek to generate targeted search queries — articles are prioritized based on your actual background and goals, not just keyword matching.

## Web Source (Any Webpage)

For sites that don't have RSS feeds, add them as `web` resources:

```bash
uv run newsletter add-resource --name "Company Blog" \
  --url "https://blog.example.com/" --type web
```

The web source uses a tiered extraction strategy — it tries each method in order and stops at the first that returns results:

| Strategy | Method | Cost | When it works |
|----------|--------|------|---------------|
| 1. JSON API | Parse structured JSON | Free | Sites with API endpoints |
| 2. RSS autodiscovery | Find linked feeds in HTML | Free | Sites with hidden RSS feeds |
| 3. Jina Reader | Markdown extraction via Jina | Free | Most standard pages |
| 4. Firecrawl | Firecrawl API extraction | ~credits | Complex JavaScript sites |
| 5. HTML structure | Extract from `<article>` tags | Free | Standard blogs |
| 6. AI fallback | Claude Haiku extracts from page | ~$0.01/page | Unusual layouts, SPAs |

Deterministic methods are tried first; AI is only used as a last resort.

### Auto-Pagination

Web sources automatically follow pagination links up to `max_pages` depth (default: 3). The agent detects next-page links using standard HTML semantics:

1. `<link rel="next">` — standard pagination hint
2. `<a rel="next">` — explicit next-page link
3. Pagination containers — `<nav>`, `<div>`, `<ul>` with pagination-related classes
4. `aria-label="next"` — accessible navigation links

This works generically across most sites without site-specific configuration.

## Web Article Search (Tavily)

Every `send` run searches the web for fresh articles via the Tavily Search API. Queries are generated by DeepSeek V4 Flash based on your `AboutMe.md` profile and configured interests — each query targets a different interest area for diverse coverage (default: 5 queries per run).

If `DEEPSEEK_API_KEY` is not set, the agent falls back to simple keyword-based queries from your interests list.

If `TAVILY_API_KEY` is not set, web search is skipped entirely and only your configured sources are fetched.

## Pipeline Stages

1. **Deterministic fetch** — RSS feeds, Reddit subreddits, web pages with auto-pagination (all DB-driven, no time filtering)
2. **Web article search** — LLM-generated Tavily queries targeting each interest area
3. **Deduplication** — Two stages: DB history (URL + title fingerprint) removes previously seen articles, then OpenAI semantic embeddings catch cross-source duplicates in the live batch
4. **Relevance filtering** — DeepSeek V4 Flash binary filter removes noise (batched at 100/call, fail-open)
5. **Ranking** — Claude ranks and summarizes remaining articles (Batch API by default, 50% cheaper)
6. **Digest** — HTML email via Resend with cost breakdown and health report

Sources fetch everything available (no time-based filtering). The two-stage dedup handles repeat articles across runs, so no articles are lost between infrequent runs.

## Run Health Report

Every `send` and `test-source` command prints a health report:

```
--- Run Health ---
  Sources:   3 OK (RSS Feeds: 511, Reddit: 41, Web Pages: 641)
  Warnings:
    - Web "Example Blog": no articles found
  Discovery: 5/5 Tavily queries OK, 42 articles
  Filter:    32 kept, 3 removed
  Ranking:   OK (batch)
  Dedup:     semantic, removed 1176
  Delivery:  sent
```

Shows per-source/feed/page results, API failures, filter stats, dedup strategy, and delivery status.

## Scheduling

Install a daily schedule with one command. Works on all platforms:

| OS | Method |
|----|--------|
| macOS | LaunchAgent (plist) via `launchctl` |
| Linux | crontab |
| Windows | Task Scheduler |

```bash
uv run newsletter install-schedule --time 08:00
uv run newsletter install-schedule --uninstall
```

## Cost

| Model | Per run | Monthly (daily) |
|-------|---------|-----------------|
| Claude Haiku (default, Batch API) | ~$0.07 | ~$2.00/month |
| Claude Sonnet (Batch API) | ~$0.14 | ~$4.20/month |

Additional per-run costs: Tavily search (~$0.05 for 5 queries), DeepSeek V4 Flash filter + query generation (~$0.001), OpenAI embeddings (~$0.003). Actual cost depends on article volume.

## Resource Management

All resources live in the SQLite database. The database starts empty — add sources manually.

```bash
# List all resources
uv run newsletter resources

# Add an RSS feed
uv run newsletter add-resource --name "Hacker News" \
  --url "https://news.ycombinator.com" \
  --feed-url "https://hnrss.org/frontpage" \
  --type blog

# Add a subreddit
uv run newsletter add-resource --name "r/programming" \
  --url "https://reddit.com/r/programming" --type subreddit

# Add a web page (auto-extracted via JSON/RSS/Jina/Firecrawl/HTML/AI)
uv run newsletter add-resource --name "Company Blog" \
  --url "https://blog.example.com/" --type web

# Remove a resource by ID
uv run newsletter remove-resource 42
```

## Sources

| Source | Method | API Key Required |
|--------|--------|-----------------|
| RSS feeds (from database) | RSS/Atom feeds via feedparser | No |
| Reddit (subreddits from database) | Public RSS feeds | No |
| Web pages (from database) | JSON → RSS → Jina → Firecrawl → HTML → AI | No (AI fallback uses Anthropic key) |

## Project Structure

```
src/newsletter_agent/
├── cli.py              # Click CLI
├── config.py           # Pydantic config
├── models.py           # Article, Priority, Digest, SourceHealth
├── pipeline.py         # Orchestrator (fetch → dedup → filter → rank → deliver)
├── report.py           # RunReport — per-run health report
├── scanner.py          # LLM-generated Tavily search queries
├── cost_tracker.py     # Per-run cost estimation
├── utils.py            # URL normalization, semantic dedup
├── scheduling.py       # LaunchAgent / crontab / Task Scheduler
├── sources/
│   ├── base.py         # BaseSource abstract class
│   ├── rss.py          # RSS/Atom feed source
│   ├── reddit.py       # Reddit source (public RSS)
│   └── web.py          # Web source (tiered extraction + auto-pagination)
├── ranking/
│   ├── ranker.py       # Claude API ranking (sync + batch)
│   └── filter.py       # DeepSeek V4 Flash relevance filter
├── delivery/
│   ├── email.py        # Resend email delivery
│   └── templates.py    # HTML digest templates
└── state/
    └── store.py        # SQLite persistence + resource database
```

## Key Features

- **3 DB-driven source types**: RSS, Reddit, Web — no hardcoded sources, everything lives in SQLite
- **Tiered web extraction**: JSON API → RSS autodiscovery → Jina Reader → Firecrawl → HTML → Claude AI fallback
- **Auto-pagination**: Web sources follow next-page links up to configurable depth using standard HTML semantics
- **No time filtering**: Sources fetch everything available; two-stage dedup handles repeats across runs — no articles lost between infrequent runs
- **LLM-generated search queries**: DeepSeek V4 Flash generates diverse Tavily queries from your profile (with keyword fallback)
- **Two-stage dedup**: DB history removes previously seen articles, OpenAI semantic embeddings catch cross-source duplicates in the live batch
- **Relevance filtering**: DeepSeek V4 Flash binary filter removes noise before expensive Claude ranking (batched at 100/call)
- **Batch API ranking**: 50% cheaper via Claude Batch API (default mode)
- **Run health report**: Every command prints source/feed/API success and failure summary
- **Source health monitoring**: Auto-disables sources after 3 consecutive failures, 24h retry cooldown
- **Digest history**: Browse past digests with search, date filters, and detail view
- **Cost tracking**: Per-run cost estimates (Tavily + DeepSeek + Claude + OpenAI) stored with each digest
- **User profile**: AboutMe.md drives personalized ranking and article search
- **Permanent article history**: `seen_articles` table is never pruned — full read history
- **Auto-load .env**: python-dotenv loads API keys automatically
- **Cross-platform scheduling**: Daily jobs on macOS (launchd), Linux (cron), Windows (Task Scheduler)

## Adding a New Source

1. Create `src/newsletter_agent/sources/my_source.py` implementing `BaseSource`
2. Register in `sources/__init__.py` SOURCE_REGISTRY
3. Add config toggle in `config.py` SourcesConfig
4. Wire up instantiation in `sources/__init__.py` `instantiate_source()`
5. Add tests in `tests/sources/test_my_source.py`

## License

MIT
