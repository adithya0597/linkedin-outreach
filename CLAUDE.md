# LinkedIn Outreach Automation — Project Context

> This file is auto-loaded by Claude Code at session start. Customize it with your own details.

## WHO I AM
<!-- Fill in your details -->
Your Name, Your Title at Your Company, Your Location.
- **Visa Status:** [Your work authorization status, if relevant]
- **Core stack:** [Your technical stack]
- **Portfolio:** [Your portfolio URL]
- **LinkedIn:** [Your LinkedIn profile]

## TARGET CRITERIA (MANDATORY FILTER)
- <1,000 employees
- Seed through Series C funding
- AI/ML as CORE product (not just "uses AI")
- USA headquarters ONLY
- **H1B SPONSORSHIP:** See `.claude/rules/h1b-filtering.md` for the three-tier system
- DISQUALIFIED: FAANG, Big Tech, consulting/staffing firms, non-US companies

## JOB SOURCES (17 scrapers across 4 tiers)

### Four-Tier Scraper Architecture
**Tier S — Zero Risk (APIs):** Ashby, Greenhouse, Hiring Cafe
**Tier A — Low Risk (httpx):** Wellfound (`__NEXT_DATA__`), YC (Algolia API), WTTJ (Algolia API), startup.jobs, Top Startups, AI Jobs
**Tier B — MCP Playwright:** LinkedIn (primary), LinkedIn Alerts (Gmail), Built In (probe), JobBoard AI (probe)
**Tier C — Patchright Stealth:** Jobright, TrueUp
**Tier D — New Sources:** JobSpy (aggregator), HN Hiring

### Three-Tier H1B Filtering System
See `.claude/rules/h1b-filtering.md` for full details.

**Tier 3 — Startup Portals (NO H1B filter):** startup.jobs, workatastartup.com (YC), topstartups.io, hiring.cafe, wellfound.com, HN Hiring
**Tier 2 — General Portals (H1B cross-check required):** ashby, greenhouse, wttj, aijobs.ai, builtin.com, jobboardai.io, trueup.io, jobright.ai, jobspy
**Tier 1 — LinkedIn (H1B cross-check required):** LinkedIn (MCP Playwright), LinkedIn Alerts (Gmail)

### H1B Verification Source Priority
1. **Frog Hire** (froghire.ai) — PRIMARY
2. **H1BGrader** (h1bgrader.com) — Secondary
3. **MyVisaJobs** (myvisajobs.com) — Secondary

### Scanning Cadence
- **First run:** LinkedIn = last 7 days. All portals = ALL current listings.
- **Subsequent runs:** ALL sources = only newly posted since last scan.
- **Dual schedule:** 8 AM full scan + 2 PM rescan (high-velocity sources)

## KEY OUTREACH RULES
See `.claude/rules/outreach-rules.md` for the full 12-rule system.

Quick reference:
- Connection requests ≤300 characters (LinkedIn Premium)
- No job ask in first contact — lead with value/expertise
- Pre-engage before connecting
- Portfolio link only in follow-ups, never in connection requests
- Match target's communication style
- InMail ≤400 chars, best timing Tue-Thu 9-11 AM recipient timezone

## NOTION CRM

### Database: Applications (Job Application Tracker)
- Set `NOTION_DATABASE_ID` in `.env` to your Notion database
- Auto-sync wired into all CLI commands that modify data (`--no-sync` to skip)

### Field Format Notes (for Notion API calls)
- Multi-select (Differentiators): Must be single string, NOT array
- URL field (Link): Plain string
- Status field (Stage): "To apply" / "Applied" / "No Answer" / "Offer" / "Rejected"

## MCP SERVERS (configured in .mcp.json)
- **Notion** — CRUD on Applications database, search, comments
- **Google Calendar** — Event management (if configured)
- **Gmail** — Email search, read, draft (if configured)

## CLI COMMANDS

### Scanning
- `outreach scan --all` — Full scan across all portals
- `outreach scan --portal <name>` — Scan a specific portal
- `outreach scan --tier <S|A|B|C>` — Scan all portals in a tier

### Validation & Research
- `outreach validate <company>` — PASS/FAIL company validation
- `outreach completeness-report` — Quality report with missing-field analysis

### Outreach
- `outreach warmup-status <company>` — Warmup state for contacts
- `outreach warmup-next` — Today's recommended warmup actions
- `outreach warmup-record <company> <contact> <action>` — Record a warmup action

### Pipeline
- `outreach workflow-next` — Suggest next action
- `outreach check-config` — Validate environment
- `outreach pipeline-status` — Last scan results and pipeline stage

### Notion Sync
- `outreach sync-notion` — Push to Notion
- `outreach notion-pull` — Pull from Notion
- `outreach notion-bidirectional` — Full bidirectional sync
