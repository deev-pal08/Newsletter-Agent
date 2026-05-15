# Newsletter Agent

Personalized research intelligence agent. Monitors curated sources, discovers new ones via web search, uses Claude to filter signal from noise, and delivers a prioritized daily digest via email.

## What It Does

1. **Profiles** you via `AboutMe.md` — your skills, experience, and learning goals
2. **Fetches** from 8 source types: RSS blogs, arXiv papers, Hacker News, GitHub Trending, Reddit, HackerOne disclosures, oss-security mailing list, and conference proceedings
3. **Discovers** new resources via `scan` — Claude + web search finds blogs, YouTube channels, podcasts, newsletters, courses, tools, communities, and anything else relevant to your profile
4. **Deduplicates** using URL normalization, title fingerprinting, and cross-source fuzzy matching
5. **Ranks** using Claude AI into four priority levels: Critical, Important, Interesting, Reference — personalized to your profile
6. **Delivers** a formatted HTML email via Resend
7. **Tracks** source health, digest history, and seen articles in SQLite
8. **Extracts** articles from any webpage — JSON APIs, RSS autodiscovery, HTML structure, or AI fallback

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
# Edit .env — paste your Anthropic and Resend API keys

# 7. Add your sources (the DB starts empty — pick one approach)
# Option A: Discover sources automatically via web search
uv run newsletter scan
# Option B: Add sources manually
uv run newsletter add-resource --name "My Blog" \
  --url "https://example.com" \
  --feed-url "https://example.com/rss" \
  --type blog

# 8. Test a source
uv run newsletter test-source hackernews

# 9. Preview a full ranked digest (requires Anthropic key)
uv run newsletter send --dry-run

# 10. Send for real (requires both keys)
uv run newsletter send

# 11. (Optional) Install daily schedule with Batch API (50% cheaper)
uv run newsletter install-schedule --batch --submit-time 23:00 --time 08:00
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

- **about_me**: Path to your `AboutMe.md` profile (default: `AboutMe.md`)
- **interests**: Your research focus areas (used by Claude for ranking)
- **sources**: Toggle source types on/off (RSS, arXiv, HN, GitHub, Reddit, etc.)
- **llm.model**: `claude-haiku-4-5` (cheap) or `claude-sonnet-4-6` (better)
- **email**: Resend delivery settings
- **dedup**: Fuzzy URL matching and title similarity threshold
- **health**: Auto-disable failing sources, retry cooldown
- **schedule**: Daily digest time and timezone

RSS feeds, subreddits, and other resources are managed in the SQLite database — use the CLI commands below to add, remove, and list them.

## Commands

| Command | Description |
|---------|-------------|
| `newsletter send` | Full pipeline: fetch, rank, email |
| `newsletter send --dry-run` | Generate HTML without sending |
| `newsletter send --batch` | Same as send, but 50% cheaper via Batch API |
| `newsletter digest` | Fetch + rank, print to terminal |
| `newsletter digest --batch` | Same as digest, using Batch API |
| `newsletter fetch` | Fetch only, print summary |
| `newsletter scan` | Discover new resources via web search |
| `newsletter scan --dry-run` | Preview discoveries without adding |
| `newsletter scan --auto` | Auto-add all discovered resources |
| `newsletter resources` | List all resources in the database |
| `newsletter add-resource` | Add a resource to the database |
| `newsletter remove-resource <ID>` | Remove a resource from the database |
| `newsletter test-source <id>` | Debug a single source |
| `newsletter sources` | Show source status and health |
| `newsletter status` | Show system state (SQLite backend) |
| `newsletter history` | Browse past digests |
| `newsletter history --detail <ID>` | View a specific past digest |
| `newsletter batch-submit` | Submit articles for async batch ranking |
| `newsletter batch-collect` | Collect results from a pending batch job |
| `newsletter batch-collect --send-email` | Collect results and send digest email |
| `newsletter install-schedule` | Install daily schedule |
| `newsletter install-schedule --batch` | Install async batch schedule (50% cheaper) |
| `newsletter install-schedule --uninstall` | Remove installed schedule |
| `newsletter re-enable <source>` | Reset error count for a source |

## Batch API (50% Cheaper)

The Claude Batch API processes requests asynchronously at half the cost. Two ways to use it:

**Inline mode** — add `--batch` to any command (waits for results, up to 60 min):
```bash
uv run newsletter send --batch --dry-run
```

**Async mode** — submit at night, collect in the morning:
```bash
# Step 1: Submit (returns immediately)
uv run newsletter batch-submit

# Step 2: Collect when ready
uv run newsletter batch-collect --send-email
```

**Automated async schedule** — set it and forget it:
```bash
uv run newsletter install-schedule --batch --submit-time 23:00 --time 08:00
```
This creates two daily jobs: submit at 11 PM, collect and email at 8 AM. Both ranking and web AI extraction are batched at 50% off.

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

The profile is injected into Claude's ranking prompts, so articles are prioritized based on your actual background and goals — not just keyword matching.

## Source Discovery (scan)

The `scan` command uses Claude Sonnet + web search to find new resources of any kind based on your profile:

```bash
# Interactive — review and pick which resources to add
uv run newsletter scan

# Preview only — see what it finds without changing the database
uv run newsletter scan --dry-run

# Add everything automatically
uv run newsletter scan --auto
```

It finds blogs (with RSS feeds), YouTube channels, podcasts, newsletters, courses, forums, communities, tools, and anything else relevant to your interests. Discovered resources are saved to the database and routed intelligently:
- Blogs with RSS feeds → `source_type='rss'` (auto-fetched daily)
- Subreddits → `source_type='reddit'` (auto-fetched daily)
- Everything else → reference only (stored for your records, not auto-fetched)

### Web Source (any webpage)

For sites that don't have RSS feeds, add them as `web` resources:

```bash
uv run newsletter add-resource --name "SonarSource Blog" \
  --url "https://www.sonarsource.com/blog/" --type web
```

The web source uses a tiered extraction strategy — it tries each method in order and stops at the first that returns results:

| Strategy | Method | Cost | When it works |
|----------|--------|------|---------------|
| 1. JSON API | Parse structured JSON | Free | Sites with API endpoints (e.g., BugBoard) |
| 2. RSS autodiscovery | Find linked feeds in HTML | Free | Sites with hidden RSS feeds |
| 3. HTML structure | Extract from `<article>` tags, heading patterns | Free | Most standard blogs |
| 4. AI fallback | Claude Haiku extracts articles from page text | ~$0.01/page | JavaScript SPAs, unusual layouts |

AI is only used as a last resort — most sites are handled deterministically at zero cost.

Run it whenever you want to expand your sources — it's not part of the daily pipeline.

## Scheduling

Install a daily schedule with one command. Works on all platforms:

| OS | Method | Created by |
|----|--------|------------|
| macOS | LaunchAgent (plist) | `launchctl load` |
| Linux | crontab | `crontab -` |
| Windows | Task Scheduler | `schtasks /Create` |

```bash
# Standard mode (full-price, instant ranking)
uv run newsletter install-schedule --time 08:00

# Batch mode (50% cheaper, async overnight)
uv run newsletter install-schedule --batch --submit-time 23:00 --time 08:00

# Remove schedule
uv run newsletter install-schedule --uninstall

# Verify (macOS)
launchctl list | grep newsletter
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for ranking, scanning, and web AI fallback |
| `RESEND_API_KEY` | Yes (for email) | Resend API key for delivery |

## Cost

| Model | Per run | Monthly (daily) | With Batch API |
|-------|---------|-----------------|----------------|
| Claude Haiku (default) | ~$0.045 | ~$1.35/month | ~$0.68/month |
| Claude Sonnet | ~$0.135 | ~$4.05/month | ~$2.03/month |

## Resource Management

All resources (RSS feeds, subreddits, web pages, and reference links) live in the SQLite database. The database starts empty — add sources yourself or let `scan` discover them for you.

```bash
# Discover sources based on your profile (recommended for first setup)
uv run newsletter scan

# List all resources in the database
uv run newsletter resources

# Add an RSS feed
uv run newsletter add-resource --name "PortSwigger Research" \
  --url "https://portswigger.net/research" \
  --feed-url "https://portswigger.net/research/rss" \
  --type blog

# Add a web page (auto-extracted via JSON/RSS/HTML/AI)
uv run newsletter add-resource --name "SonarSource Blog" \
  --url "https://www.sonarsource.com/blog/" --type web

# Remove a resource by ID
uv run newsletter remove-resource 42
```

On first run, the database is empty. Use `scan` to auto-discover sources based on your profile, or add them manually with `add-resource`.

## Sources

| Source | Method | API Key Required |
|--------|--------|-----------------|
| RSS feeds (from database) | RSS/Atom feeds | No |
| arXiv | Public API | No |
| Hacker News | Firebase API | No |
| GitHub Trending | HTML scraping | No |
| Reddit (subreddits from database) | Public RSS | No |
| Web pages (from database) | JSON/RSS/HTML/AI extraction | No (AI fallback uses Anthropic key) |
| oss-security | Web scraping | No |
| HackerOne | GraphQL (experimental) | No |
| Conferences | Web scraping | No |

## Project Structure

```
src/newsletter_agent/
├── cli.py              # Click CLI (15 commands)
├── config.py           # Pydantic config
├── models.py           # Article, Priority, Digest, SourceHealth
├── pipeline.py         # Orchestrator (fetch → dedup → rank → deliver)
├── scanner.py          # Source discovery (Claude + web search)
├── utils.py            # URL normalization, title similarity
├── scheduling.py       # LaunchAgent / crontab / Task Scheduler
├── sources/            # Source plugins (one per file, incl. web.py)
├── ranking/            # Claude API ranking (sync + batch)
├── delivery/           # Resend email + templates
└── state/              # SQLite persistence + resource database
```

## v2 Features

- **SQLite state**: Replaced JSON with SQLite (WAL mode). Auto-migrates from v1 `state.json` on first run.
- **Fuzzy dedup**: URL normalization (strips tracking params, www, trailing slash), title fingerprinting, cross-source title similarity matching (85% threshold).
- **Source health monitoring**: Auto-disables sources after 3 consecutive failures, retries after 24h cooldown. Use `re-enable` to reset manually.
- **Digest history**: Browse past digests with `--since`, `--until`, `--search`, and `--detail` options.
- **Batch API**: 50% cheaper ranking via Claude's Batch API. Supports inline (`--batch` flag) and async (`batch-submit` / `batch-collect`) modes. In async mode, web AI extraction is also batched for additional savings.
- **Cross-platform scheduling**: Install daily jobs on macOS (launchd), Linux (cron), or Windows (Task Scheduler). Supports both sync and async batch modes.
- **User profile**: `AboutMe.md` personalizes ranking and source discovery based on your background, skills, and learning goals. Works for any domain — security, baking, design, finance, anything.
- **Source scanner**: `scan` command uses Claude Sonnet + web search to discover blogs, YouTube channels, podcasts, newsletters, courses, tools, communities, and any other resources matching your profile.
- **DB-backed resources**: All RSS feeds, subreddits, web pages, and discovered resources are stored in SQLite. No hardcoded URLs — the database starts empty and users populate it via `scan` or `add-resource`.
- **Web source (AI-assisted)**: Generic `source_type='web'` extracts articles from any webpage using a tiered strategy: JSON API → RSS autodiscovery → HTML structure → Claude Haiku AI fallback. Deterministic methods are tried first; AI is only used when they fail. In async batch mode, AI extraction is deferred and submitted via Batch API for 50% savings.
- **Permanent article history**: The `seen_articles` table is never pruned, serving as both a dedup index and a permanent read history of every article ever processed.

## Adding a New Source

1. Create `src/newsletter_agent/sources/my_source.py` implementing `BaseSource`
2. Register in `sources/__init__.py` SOURCE_REGISTRY
3. Add config toggle in `config.py` SourcesConfig
4. Wire up instantiation in `sources/__init__.py` `instantiate_source()`

## License

MIT
