# LinkedIn Outreach Swarm — Persistent Session Context

> This file is auto-loaded by Claude Code at session start. It contains all project context, rules, and conventions.

## WHO I AM
Bala Adithya Malaraju, AI Engineer at Infinite Computer Solutions, Irving TX.
- **Visa Status:** F1 Student Visa — REQUIRES H1B sponsorship
- **Core stack:** Python, LangChain, Neo4j, Milvus, FastAPI, AWS, Java/Spring Boot
- **Killer stats:** 138-node semantic graph, 90% automated code translation across 27 microservices, 26,000+ orders via agentic pipeline, 300+ table healthcare CDC pipelines (99.9% integrity)
- **Portfolio:** https://bala-adithya-malaraju.vercel.app/
- **LinkedIn:** Bala Adithya Malaraju
- **Profile Strength:** AI *Engineering* and *Infrastructure* (production systems that use AI/ML — NOT deep ML research/model training)

## TARGET CRITERIA (MANDATORY FILTER)
- <1,000 employees
- Seed through Series C funding
- AI/ML as CORE product (not just "uses AI")
- USA headquarters ONLY
- **H1B SPONSORSHIP:** See `.claude/rules/h1b-filtering.md` for the three-tier system
- DISQUALIFIED: FAANG, Big Tech, consulting/staffing firms, non-US companies, companies that explicitly won't sponsor H1B

## PROJECT FILES (in this folder)

### Core System
- `CLAUDE.md` — This file (auto-loaded by Claude Code)
- `COWORK_SWARM_PROMPT.md` — Master 5-agent swarm prompt (v2.0)
- `COWORK_CHEATSHEET.md` — Quick reference for all templates and rules
- `PROJECT_GUIDE.md` — Complete operating guide (workflow, skills, prompts, schedule)

### Targets & Tracking
- `Startup_Target_List.md` — 100 targets across 5 tiers + portal scan status
- `Company_Tracker.xlsx` — Spreadsheet tracker with COUNTIF formulas
- `Portal_Analytics.md` — Per-portal performance metrics for scan frequency decisions

### Templates & Outreach
- `Message_Templates.md` — 10 outreach templates (0-9) with character counts
- `Tier1_Outreach_Master.md` — 12 Tier 1 companies with full outreach packages + clickable LinkedIn links
- `Hippocratic_AI_3_Outreach_Messages.md` — Ready to send
- `Pair_Team_Outreach.md` — Ready to send (includes Fredy C.)
- `Startup_Recruiter_Connection_Requests.md` — 4 recruiter messages

### Scan Logs
- `Daily_Scan_2026-03-05_Rescan.md` — Latest scan results
- `Today_Actions_2026-03-05.md` — Daily action items

### Config (Claude Code specific)
- `.mcp.json` — MCP server configuration (Notion, Gmail, Calendar)
- `.claude/skills/` — 5 custom skills (migrated from Cowork)
- `.claude/rules/` — H1B filtering rules, outreach rules

## CUSTOM SKILLS (in .claude/skills/)
Use these as slash commands in Claude Code:
- `/daily-portal-scanner` — Scans all 13 sources with three-tier H1B filtering
- `/outreach-drafter` — Generates full outreach packages (Steps 0-5)
- `/company-validator` — PASS/FAIL company validation against target criteria
- `/hiring-manager-finder` — Finds CTO/VP Eng/Recruiter on LinkedIn
- `/application-tracker` — Logs outreach, surfaces follow-ups

## OUTREACH STATUS

### Ready to Send (not yet sent)
1. **Hippocratic AI** → Sakshi Palta (Recruiter, 2nd degree) — `Hippocratic_AI_3_Outreach_Messages.md`
2. **Pair Team** → Aaron Tyler (SVP Eng, 3rd+) — `Pair_Team_Outreach.md`
3. **4 Startup Recruiters** — `Startup_Recruiter_Connection_Requests.md`
4. **Fredy C.** (Dallas AI recruiter, 2nd degree) — in `Pair_Team_Outreach.md`
5. **12 Tier 1 Companies** — Full packages in `Tier1_Outreach_Master.md`

### Removed
- ~~Hypercubic~~ — Does not sponsor H1B
- ~~Irina Adamchic~~ — Not in United States

### Messages Sent Log
| Date | Target | Action | Response |
|------|--------|--------|----------|
| — | — | No messages sent yet | — |

## TIER 1 COMPANIES (12 — Full Outreach Ready)

| # | Company | Contact | Fit | H1B |
|---|---------|---------|-----|-----|
| 1 | Kumo AI | Hema Raghavan (Head Eng) | 91 | Unknown |
| 2 | LlamaIndex | Simon Suo (CTO) | — | Confirmed |
| 3 | Cursor | Aman Sanger (Co-Founder) | 90 | Confirmed |
| 4 | Hippocratic AI | Sakshi Palta (Recruiter) | 90 | Confirmed |
| 5 | LangChain | Allison Ewing (Sr Recruiter) | 85 | Likely |
| 6 | Norm AI | Tessa Corbishley (TA) | — | Confirmed |
| 7 | Spherecast (YC) | Leon Hergert (Founder) | — | Tier 3 |
| 8 | Cinder | Glen Wise (CEO) | — | Confirmed |
| 9 | Augment Code | TBD | 90 | Confirmed |
| 10 | Pair Team | Brittany Rowles (Recruiter) | 88 | Confirmed |
| 11 | Snorkel AI | Curtis Tuttle (Lead Recruiter) | 87 | Confirmed |
| 12 | EvenUp | Erica Sahli (Talent Lead) | — | Confirmed |

> **Note on Kumo AI:** Fit score is high due to graph ML domain match, but Adithya's profile is AI *engineering* (production systems, pipelines, infrastructure) — NOT deep ML research. Kumo may need a GNN researcher, not an AI engineer. Validate the actual JD before prioritizing.

## JOB SOURCES (13 total — 12 portals + LinkedIn)

### Three-Tier H1B Filtering System
See `.claude/rules/h1b-filtering.md` for full details.

**Tier 3 — Startup Portals (NO H1B filter):** startup.jobs, workatastartup.com (YC), topstartups.io, hiring.cafe, wellfound.com

**Tier 2 — General Portals (H1B cross-check required):** jobboardai.io, aijobs.ai, welcometothejungle, builtin.com, trueup.io, jobright.ai, froghire.com

**Tier 1 — LinkedIn (H1B cross-check required):** LinkedIn — 13th source

### H1B Verification Source Priority
1. **Frog Hire** (froghire.ai) — PRIMARY → https://www.froghire.ai/company
2. **H1BGrader** (h1bgrader.com) — Secondary
3. **MyVisaJobs** (myvisajobs.com) — Secondary

### Scanning Cadence
- **First run:** LinkedIn = last 7 days. All portals = ALL current listings.
- **Subsequent runs:** ALL sources = only newly posted since last scan.
- **Dual schedule:** 8 AM full scan (13 sources) + 2 PM rescan (9 high-velocity sources)
- **Frequency review:** Weekly via Portal_Analytics.md scoring (0–12 rubric)

**Last scan:** 2026-03-05 PM — ALL 13 SOURCES RESCANNED. 100 total entries.

## LINKEDIN PREMIUM CAREER (ACTIVE — renews Mar 26, 2026)

### Key Features to Exploit
- **300-char connection requests** (vs 200 free)
- **InMail credits (5-15/month):** For 3rd+ degree targets. Check Open Profile first (FREE InMail)
- **Unlimited People Browsing:** No monthly search cap
- **Who Viewed Your Profile:** Check DAILY — viewers from target companies = WARM LEADS
- **Top Applicant badge:** Scan daily. Skip Easy Apply + pure Data Engineer roles
- **Top Choice Jobs:** Mark best-fit jobs to signal strong interest
- **Open Profile:** ENABLED — anyone can send FREE InMail to Adithya
- **Premium Profile Badge:** ENABLED — credibility signal

### LinkedIn Scan Rules
- Ignore Easy Apply
- Ignore pure Data Engineer without AI
- Prioritize Top Applicant badge
- Mark Top Choice on best-fit jobs (Fit ≥ 8)

## KEY OUTREACH RULES
See `.claude/rules/outreach-rules.md` for the full 12-rule system.

Quick reference:
- Connection requests ≤300 characters (PREMIUM)
- No job ask in first contact — lead with value/expertise
- Pre-engage before connecting (EXCEPT profile viewer warm leads)
- Portfolio link only in follow-ups, never in connection requests
- Match target's communication style
- No: "pick your brain", "just reaching out", "hope this finds you well"
- InMail ≤400 chars, best timing Tue-Thu 9-11 AM recipient timezone

## NOTION CRM

### Database: Applications (Job Application Tracker)
- **Database ID:** `0c412604-a409-47ab-8c04-29f112c2c683`
- **Parent Page:** `f6b465c896f74dfbac30ca6a5f718140`
- **100 company entries** with: Tier, Fit Score, H1B Status, Stage, Hiring Manager, Link, Salary, Notes
- **Schema fields:** Company (Title), Tier (Select), Fit Score (Number), H1B Sponsorship (Select), Stage (Status), Position (Text), Hiring Manager (Text), Link (URL), Salary Range (Text), Source Portal (Select), Notes (Text), Differentiators (Multi-select), Applied Date (Date), Follow Up (Date)

### Field Format Notes (for Notion API calls)
- Multi-select (Differentiators): Must be single string, NOT array
- URL field (Link): Plain string
- Status field (Stage): "To apply" / "Applied" / "No Answer" / "Offer" / "Rejected"

### LinkedIn Contacts Database
- 7+ contacts with degree/status/outreach stage

### Daily Portal Scan Log
- Scan history with portal coverage

## MCP SERVERS (configured in .mcp.json)
- **Notion** — CRUD on Applications database, search, comments
- **Google Calendar** — Event management (if configured)
- **Gmail** — Email search, read, draft (if configured)

## SESSION LOG
| Date | What Was Done |
|------|---------------|
| 2026-03-04 | Sessions 1-4: Built swarm v2.0, 11 portals, 26 targets, outreach drafts, Notion CRM, 5 skills, H1B filtering, Frog Hire verification (6/7 confirmed) |
| 2026-03-05 | Sessions 5-10: Three-tier H1B encoding, PROJECT_GUIDE, Portal_Analytics, dual-scan schedule, FULL 13-source scan (100 entries), portal rankings (Jobright #1, Hiring Cafe #2) |
| 2026-03-05 | Sessions 11-14: LinkedIn deep scan (+10 companies), Premium integration (300 chars, InMail, 8 features), 2026 best practices audit (9.2/10), full Premium catalog (P1-P8) |
| 2026-03-05 | Session 15: Full 13-source rescan, 18 new companies, H1B cross-checks, total 100 entries |
| 2026-03-05 | Session 16: Populated Link + Hiring Manager fields for ~55 companies via Notion API (90/100 with URLs, 87/100 with contacts) |
| 2026-03-05 | Session 17: Identified all 12 Tier 1 companies, researched LinkedIn contacts, drafted full outreach packages (Steps 0-5) for all 12, saved to Tier1_Outreach_Master.md with clickable links |
| 2026-03-05 | Session 18: Added LinkedIn profile URLs, company pages, careers links, and activity feed links to every step of Tier1_Outreach_Master.md. Created Claude Code migration package (setup script, updated CLAUDE.md, MCP config) |
