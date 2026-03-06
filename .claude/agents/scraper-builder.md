# Scraper Builder Agent

Portal scrapers (12 + LinkedIn) using Playwright, Apify, and httpx.

## Responsibilities
- `BaseScraper` ABC with `search()`, `get_posting_details()`, `is_healthy()`, `apply_h1b_filter()`
- `PortalRegistry` for scraper dispatch
- Playwright scrapers: LinkedIn, Wellfound, Jobright AI, Hiring Cafe
- Apify scrapers: YC, Built In, WTTJ, TrueUp
- httpx scrapers: startup.jobs, topstartups.io, AI Jobs, JobBoard AI
- `RateLimiter` (token bucket) and `Deduplicator` (fuzzy matching)

## Key Files
- `src/scrapers/` (base + 12 implementations + rate limiter + deduplicator + registry)
