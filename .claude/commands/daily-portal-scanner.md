---
name: daily-portal-scanner
description: "**Daily Job Portal Scanner**: Scans 19 job sources across 4 tiers (APIs, httpx, MCP Playwright, Patchright stealth) with three-tier H1B filtering for new roles matching startup criteria (under 1000 employees, Seed-Series C, AI-native, US HQ). Use this skill whenever the user mentions scanning portals, checking job boards, finding new jobs, daily scan, job search update, new listings, portal check, or wants to discover fresh AI/ML engineering roles. Also trigger when the user says things like 'any new jobs today', 'check for openings', 'scan for roles', or 'what's new on the job boards'. This is the primary job discovery tool."
---

# Daily Portal Scanner — 4-Tier Architecture

Scan 19 job sources across 4 tiers for new AI/ML engineer roles using three-tier H1B filtering.

## Context

Scanning for Bala Adithya Malaraju, AI Engineer on F1 visa requiring H1B sponsorship. Specializes in Graph RAG, Enterprise LLM pipelines, healthcare data. Goal: find AI-native startups matching strict criteria.

## Target Criteria

- **Employees:** <1,000
- **Funding:** Seed through Series C
- **Product:** AI/ML as CORE product
- **Location:** USA headquarters ONLY
- **H1B:** Tiered filtering (see below)
- **Disqualified:** FAANG, Big Tech, consulting/staffing, non-US, explicit no-H1B

## Scan Architecture — 4 Phases

### Phase 1: Tier S — Zero Risk APIs (run first, ~30 seconds)
```
python -m src.cli.main scan --portal ashby
python -m src.cli.main scan --portal greenhouse
python -m src.cli.main scan --portal lever
python -m src.cli.main scan --portal hiring_cafe
```
These hit structured JSON APIs directly. No anti-bot risk. Run all simultaneously.

### Phase 2: Tier A — Low Risk httpx (run second, ~2 minutes)
```
python -m src.cli.main scan --portal wellfound    # __NEXT_DATA__ JSON
python -m src.cli.main scan --portal yc            # Algolia API
python -m src.cli.main scan --portal wttj          # Algolia API
python -m src.cli.main scan --portal startup_jobs   # httpx + BeautifulSoup
python -m src.cli.main scan --portal top_startups   # httpx + BeautifulSoup
python -m src.cli.main scan --portal ai_jobs        # httpx + BeautifulSoup
python -m src.cli.main scan --portal hn_hiring      # HN Who is Hiring
```
No browser needed. Run sequentially to respect rate limits.

### Phase 3: Tier B — MCP Playwright (run third, interactive)

**LinkedIn (PRIMARY):** Use the `/scan-linkedin` skill.
- MCP Playwright with logged-in session
- Safety limits: max 5 pages, 3-7s delays, 1 scan/day
- CAPTCHA detection → immediate stop

**LinkedIn Alerts (SUPPLEMENTARY):** Run first to get baseline.
- Check Gmail for LinkedIn Job Alert emails (from:jobs-noreply@linkedin.com)
- Parse HTML for job cards → persist to DB
- Zero detection risk

**Built In & JobBoard AI (PROBES):**
- Use `/scan-builtin` and `/scan-jobboard-ai` skills
- These were previously demoted — probe to check current state
- Only run if time permits

### Phase 4: Tier C — Patchright Stealth (run last, ~3 minutes)
```
python -m src.cli.main scan --portal jobright
python -m src.cli.main scan --portal trueup
```
Uses Patchright (CDP leak patched) + behavioral mimicry. Run one at a time.
If CAPTCHA/block detected → stop immediately, fall back to MCP skill.

### Phase 5: Tier D — New Sources (optional, bonus coverage)
```
python -m src.cli.main scan --portal jobspy
```
JobSpy aggregator (Indeed, Glassdoor, ZipRecruiter). Run if other phases complete quickly.

## THREE-TIER H1B FILTERING SYSTEM

### Tier 3 — Startup Portals: NO H1B filter
Add ALL matching companies. Do NOT cross-check H1B.
- Wellfound, YC, startup.jobs, Hiring Cafe, Top Startups, HN Hiring

### Tier 2 — General Portals: H1B cross-check required
Cross-check: Frog Hire → H1BGrader → MyVisaJobs. Include UNLESS explicit "no sponsorship."
- AI Jobs, WTTJ, Built In, TrueUp, Jobright, Ashby, Greenhouse, Lever, JobBoard AI, JobSpy

### Tier 1 — LinkedIn: H1B cross-check required (same as Tier 2)
- LinkedIn (MCP Playwright), LinkedIn Alerts (Gmail)

### H1B Verification Priority
1. **Frog Hire** (froghire.ai) — PRIMARY
2. H1BGrader / MyVisaJobs — Secondary
3. No data = still include, mark "Unknown"

## Quick Scan Mode
For a quick scan of just the fastest sources:
```
python -m src.cli.main scan --portal ashby
python -m src.cli.main scan --portal greenhouse
python -m src.cli.main scan --portal hiring_cafe
python -m src.cli.main scan --portal yc
python -m src.cli.main scan --portal wellfound
```

## Full Scan (all programmatic sources)
```
python -m src.cli.main scan --portal all --smart --days 7
```

## Output

Create `Daily_Scan_[YYYY-MM-DD].md` with:
- Scan summary by tier (S/A/B/C/D)
- New leads table (tier, H1B status, source)
- Portal health status
- H1B verification log
- Actions needed

Update: Notion CRM, Portal_Analytics.md, Startup_Target_List.md.
