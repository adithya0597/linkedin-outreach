# LinkedIn Outreach Automation

An end-to-end job search automation system that discovers startup job postings across 17+ sources, validates companies against targeting criteria, manages outreach sequences, and syncs everything to a Notion CRM — all from a single CLI.

Built for job seekers targeting early-stage AI startups that sponsor H1B visas.

## Architecture

```
src/
  cli/            # 16 Typer command modules (scan, outreach, validate, etc.)
  config/         # Settings, enums, startup validation checks
  dashboard/      # Streamlit real-time dashboard
  db/             # SQLAlchemy ORM, FTS5 search, H1B seed data
  integrations/   # Notion (bidirectional sync), Gmail, Google Calendar bridges
  models/         # Pydantic/SQLAlchemy models (Company, Contact, JobPosting, etc.)
  outreach/       # Template engine, personalization, warmup tracker, A/B testing
  pipeline/       # Orchestrator, scheduler, health monitor, quality gates
  scrapers/       # 17 scrapers across 4 tiers + rate limiter + circuit breaker
  validators/     # Company validator, H1B verifier, scoring engine
```

## Four-Tier Scraper Architecture

| Tier | Method | Sources | Risk |
|------|--------|---------|------|
| **S** | Direct APIs | Ashby, Greenhouse, Hiring Cafe | Zero |
| **A** | httpx + parsing | Wellfound, YC (Algolia), WTTJ, startup.jobs, Top Startups, AI Jobs | Low |
| **B** | MCP Playwright | LinkedIn, LinkedIn Alerts (Gmail), Built In, JobBoard AI | Medium |
| **C** | Patchright (stealth) | Jobright, TrueUp | High |

Each tier has its own rate limiting, retry logic, and circuit breaker protection.

## Key Features

- **Multi-source scanning** — 17 scrapers run concurrently with configurable parallelism
- **Three-tier H1B filtering** — Tier 1 (LinkedIn), Tier 2 (general portals), Tier 3 (startup-only portals with no filter)
- **Company validation** — Employee count, funding stage, AI-native product, US HQ, H1B sponsorship
- **Bidirectional Notion sync** — 43-field mapping with conflict resolution (NEWEST_WINS strategy)
- **Outreach engine** — Template-based personalization across 5 domains with A/B testing
- **Warmup tracking** — Pre-engagement actions (post likes, comments) before connection requests
- **Pipeline orchestration** — Daily scheduling with auto-promotion/demotion of portals based on yield
- **Circuit breaker** — 3-state machine (closed/open/half-open) prevents cascading scraper failures
- **Full-text search** — SQLite FTS5 across companies, postings, and contacts
- **Streamlit dashboard** — Real-time portal health, scan metrics, and pipeline status

## Quick Start

### Prerequisites

- Python 3.11+
- Google Chrome (for Playwright/Patchright scrapers with authenticated sessions)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
git clone https://github.com/<your-username>/linkedin-outreach.git
cd linkedin-outreach

# Install dependencies
uv sync          # or: pip install -e ".[dev]"

# Copy environment template and fill in your keys
cp .env.example .env
# Edit .env with your Notion API key, Apify token, etc.
```

### Configuration

1. **Environment variables** (`.env`):
   ```
   NOTION_API_KEY=your_notion_integration_token
   NOTION_DATABASE_ID=your_notion_database_id
   APIFY_TOKEN=your_apify_token          # Optional: for Apify-based scrapers
   ANTHROPIC_API_KEY=your_anthropic_key   # Optional: for LLM-based classification
   ```

2. **Portal config** (`config/portals.yaml`): Configure which job sources to scan, tier assignments, and scan schedules.

3. **Targeting criteria** (`config/criteria.yaml`): Set employee count limits, funding stages, and disqualification rules.

4. **Chrome profile**: Playwright/Patchright scrapers use your Chrome profile for authenticated sessions on LinkedIn, Wellfound, etc. Set `CHROME_PROFILE_DIR` in `.env` or use the default path.

### Usage

```bash
# Validate environment setup
outreach check-config

# Run a full scan across all portals
outreach scan --all

# Scan specific portals or tiers
outreach scan --portal linkedin
outreach scan --tier S

# Validate a company against targeting criteria
outreach validate "Company Name"

# Check pipeline status
outreach pipeline-status

# Get next recommended action
outreach workflow-next

# View completeness report
outreach completeness-report

# Sync with Notion CRM
outreach notion-sync
outreach notion-push
outreach notion-pull

# Warmup tracking
outreach warmup-status "Company Name"
outreach warmup-next
outreach warmup-record "Company" "Contact" "liked_post"

# Launch Streamlit dashboard
streamlit run src/dashboard/app.py
```

### Running Tests

```bash
# Run all tests (excludes live browser tests by default)
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test module
pytest tests/test_company_validator.py
```

## Project Structure

```
config/
  portals.yaml           # Portal definitions, tiers, scan schedules
  criteria.yaml          # Company targeting criteria
  outreach_rules.yaml    # Outreach rules and character limits

data/                    # Local SQLite database (gitignored)

src/
  cli/main.py            # Typer app entry point
  scrapers/
    base_scraper.py      # Abstract base with tier-aware H1B filtering
    ats_scraper.py       # Ashby + Greenhouse API scrapers
    algolia_scraper.py   # YC + WTTJ via Algolia search APIs
    httpx_scraper.py     # BeautifulSoup-based scrapers for static sites
    linkedin_scraper.py  # MCP Playwright LinkedIn scraper
    patchright_scraper.py # Stealth browser for anti-bot portals
    concurrent_runner.py # asyncio.TaskGroup parallel execution
    circuit_breaker.py   # 3-state failure protection
    rate_limiter.py      # Token bucket per-portal rate limiting
  integrations/
    notion_sync.py       # Bidirectional Notion sync with 43-field mapping
    notion_bidirectional.py # Conflict resolution engine
  outreach/
    template_engine.py   # Jinja2 outreach templates
    personalizer.py      # 5-domain personalization
    warmup_tracker.py    # Pre-engagement tracking
    ab_testing.py        # Template A/B experiments
  pipeline/
    daily_orchestrator.py # Dual-schedule scan orchestration
    auto_promotion.py    # Portal yield-based promotion/demotion
    health_monitor.py    # Scraper health tracking

tests/                   # 95+ test files, 1500+ tests
```

## How It Works

1. **Scan**: The daily orchestrator runs scrapers across all configured portals, deduplicates results, and persists new job postings to the local SQLite database.

2. **Filter**: Each posting goes through three-tier H1B filtering. Companies are validated against targeting criteria (employee count, funding stage, AI-native, US HQ).

3. **Enrich**: Validated companies are enriched with H1B sponsorship data from FrogHire/H1BGrader/MyVisaJobs, hiring manager contacts, and LinkedIn research.

4. **Score**: A deterministic scoring engine ranks companies by fit (funding stage, team size, tech stack alignment, H1B confidence).

5. **Outreach**: The template engine generates personalized connection requests, InMails, and follow-up sequences. A warmup tracker manages pre-engagement actions.

6. **Sync**: Bidirectional Notion sync keeps the local database and Notion CRM in lockstep with 43-field mapping and NEWEST_WINS conflict resolution.

7. **Monitor**: The Streamlit dashboard and CLI commands provide real-time visibility into portal health, scan yield, and pipeline status.

## Tech Stack

- **Language**: Python 3.11+
- **CLI**: Typer + Rich
- **Database**: SQLite + SQLAlchemy ORM + FTS5
- **Web scraping**: httpx, BeautifulSoup4, Playwright, Patchright
- **Browser automation**: MCP Playwright (for authenticated portals)
- **API clients**: Apify, Algolia, Notion API
- **Templates**: Jinja2
- **Dashboard**: Streamlit
- **Task scheduling**: APScheduler
- **Resilience**: tenacity (retries), custom circuit breaker, token bucket rate limiter
- **Testing**: pytest, pytest-asyncio, pytest-cov
- **Linting**: Ruff

## License

MIT
