# Tools, Skills & Plugins — Job Search Automation Stack

**Date:** 2026-03-04 (Updated)
**Project:** LinkedIn Outreach Automation (5-Agent Swarm)
**Focus:** Job search automation — daily portal scanning, persistent memory, outreach tracking

---

## 1. PERSISTENT MEMORY — claude-mem Plugin

### What It Solves
Every Cowork/Claude Code session starts fresh. You lose context about which messages were sent, who responded, what research was done. claude-mem fixes this by automatically capturing session activity and injecting relevant context into future sessions.

### claude-mem (by thedotmack)
**GitHub:** https://github.com/thedotmack/claude-mem
**Type:** Claude Code Plugin (installable from marketplace)

**What it does:**
- Auto-captures everything Claude does during sessions (tool usage, file edits, research)
- Compresses session data with AI into semantic summaries
- Injects relevant context back into future sessions automatically
- ChromaDB vector storage for semantic search across ALL past sessions
- Local-only storage (your data stays on your machine)

**MCP Tools provided:**
1. `search()` — Search past observations by query and type
2. `get_observations()` — Fetch full details of specific observations by ID
3. `save_memory()` — Manually save important information

**Installation:**
```bash
# In Claude Code terminal:
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem
# Restart Claude Code
```

**How it helps this project:**
- Remembers which targets you've already researched
- Tracks which messages were sent and when
- Recalls what worked in previous outreach (response rates, angles)
- Maintains continuity across daily portal scanning sessions
- Never re-researches a company you've already profiled

**Architecture:**
- 5 lifecycle hooks: SessionStart → UserPromptSubmit → PostToolUse → Summary → SessionEnd
- Worker service: Express API on port 37777, Bun-managed
- Database: SQLite3 at `~/.claude-mem/claude-mem.db`
- Web viewer UI at `http://localhost:37777` for browsing memories

**Beta features:**
- Endless Mode — biomimetic memory architecture for extended sessions
- Dual-tag privacy system (v7.0.0+)
- 11 configuration settings

### Alternative Memory Options

| Tool | Type | Best For |
|------|------|----------|
| **memsearch ccplugin** (Zilliz/Milvus) | Claude Code Plugin | Lightweight alternative — one Markdown file per day, human-readable |
| **claude-supermemory** (Supermemory AI) | Claude Code Plugin | Team memory — shares context across team members (requires Pro) |
| **CLAUDE.md** | Built-in file | Manual persistent instructions — put swarm rules + campaign status here |
| **Auto Memory** | Built-in | Auto-saves learnings — toggle with `/memory` command |

### Priority: ⭐ Install claude-mem FIRST — it's the highest-impact single addition to this project.

---

## 2. JOB PORTAL SCANNING — Daily Automation

### What It Solves
You have 13 job sources (12 portals + LinkedIn) to monitor. Manually checking each one is tedious and things get stale. You need daily automated scanning.

### Option A: Scheduled Task + Claude in Chrome (Recommended)

Use the **schedule skill** (already installed) to create a daily recurring task that:
1. Opens each portal in Chrome
2. Searches for AI/ML engineer roles (RAG, LLM, knowledge graph)
3. Extracts new listings since last scan
4. Compares against existing Startup_Target_List.md
5. Flags NEW roles not previously seen
6. Finds hiring managers on LinkedIn for new roles
7. Updates Startup_Target_List.md

**Setup:**
```
/schedule → "daily-portal-scan"
Cron: 0 8 * * 1-5  (weekdays at 8 AM local time)
```

**Task prompt for the scheduled scan:**
```
Scan these 13 job sources (12 portals + LinkedIn) for new AI/ML engineer roles in the US:
1. startup.jobs — search "AI Engineer"
2. workatastartup.com — search "AI engineer LLM"
3. wellfound.com/role/ai-engineer — browse listings
4. aijobs.ai/jobs — search "AI engineer" location "United States"
5. builtin.com/jobs/ai-machine-learning — filter startups
6. topstartups.io — search AI/ML roles
7. hiring.cafe — search "AI engineer"
8. jobright.ai/jobs — check recommendations
9. trueup.io — check saved searches
10. jobboardai.io/jobs — search AI engineer
11. app.welcometothejungle.com — search AI engineer

For each portal:
- Filter: USA only, <1000 employees, AI-native companies
- Extract: Company name, role title, salary range, location, posting date
- Compare against /mnt/lineked outreach/Startup_Target_List.md
- Flag any NEW listings not already in the target list
- Update the JOB PORTALS TO SCAN WEEKLY table with scan date and findings

Save results to /mnt/lineked outreach/Daily_Scan_[DATE].md
```

### Option B: Firecrawl Plugin (For Advanced Scraping)

**What it is:** Official Claude Code plugin for web scraping — handles JavaScript rendering, anti-bot detection, proxy rotation, outputs clean markdown/JSON.

**Installation:**
```bash
# In Claude Code:
/plugin install firecrawl
```

**Why useful:** Some portals (like Wellfound, Jobright) have complex JavaScript rendering that basic scraping misses. Firecrawl handles this automatically. Can scrape single pages OR crawl entire sections of a site.

**Best for:** Bulk-extracting all AI/ML roles from a portal in one shot, rather than manually scrolling.

### Option C: Apify Actors (Heavy-Duty Scraping)

Already available in your setup. Useful actors:

| Actor | Use Case |
|-------|----------|
| **Web Scraper** | Scrape structured job data from any portal |
| **Google Search Scraper** | Find new startup funding announcements, AI job postings |
| **Website Content Crawler** | Deep-crawl a company's careers page for all openings |

---

## 3. CUSTOM SKILLS TO BUILD

These are the skills that would actually help a **job seeker** (not a salesperson):

### Skill 1: `daily-portal-scanner` ⭐ HIGHEST PRIORITY
- **Trigger:** "scan portals", "check job boards", "find new jobs"
- **What:** Opens all 13 sources, searches with your keywords, extracts new listings, compares against existing list, flags new ones
- **Why:** Makes the daily scan a one-command operation instead of 30+ minutes of manual browsing
- **Build with:** Skill Creator + Schedule skill for daily automation

### Skill 2: `outreach-drafter`
- **Trigger:** "draft outreach for [company]", "write connection request"
- **What:** Takes a target profile → generates full outreach package (pre-engagement comment, connection request ≤250 chars, follow-up, multi-touch calendar) following all swarm rules
- **Why:** Each outreach package currently takes 20-30 min to craft manually

### Skill 3: `company-validator`
- **Trigger:** "validate [company]", "is this a fit", "check startup"
- **What:** Auto-checks: employee count (<1000), funding stage (Seed-Series C), AI-native product, US HQ, technical leadership → PASS/FAIL
- **Why:** The startup filter has strict rules that need checking every time

### Skill 4: `hiring-manager-finder`
- **Trigger:** "find hiring manager at [company]", "who's hiring at"
- **What:** Searches LinkedIn for CTO/VP Eng/Engineering Manager/Recruiter at the target company, returns name + degree + followers + recent posts for pre-engagement
- **Why:** The portal→LinkedIn pipeline requires this step for every new lead

### Skill 5: `application-tracker`
- **Trigger:** "log application", "update status", "track outreach"
- **What:** Updates Company_Tracker.xlsx and Startup_Target_List.md with sent dates, response status, follow-up reminders. Alerts on overdue follow-ups.
- **Why:** Manual tracking is error-prone and things fall through the cracks

---

## 4. CONNECTORS THAT ACTUALLY HELP JOB SEEKERS

You're right that Apollo, Clay, Outreach etc. are sales tools. Here's what's actually useful:

### Actually Useful Connectors

| Connector | Why a Job Seeker Needs It | Status |
|-----------|--------------------------|--------|
| **Notion** | Build an outreach CRM — track targets, applications, interviews, follow-ups | ✅ ALREADY CONNECTED |
| **Gmail** | Send follow-up emails to recruiters, track who responded, search for interview confirmations | Available to connect |
| **Google Calendar** | Schedule interviews, set follow-up reminders, block time for daily outreach | Available to connect |
| **Google Drive** | Store resume versions, cover letters, portfolio docs — share links in outreach | Available to connect |
| **Make** (automation platform) | Build automated workflows: new job posting → Notion entry → outreach draft → reminder | Available to connect |
| **n8n** (automation) | Same as Make but self-hosted/open-source — build job monitoring pipelines | Available to connect |

### What NOT to Connect (Sales Tools — Not Relevant)
- ~~Apollo.io~~ — Sales prospecting, not job search
- ~~Clay~~ — Account enrichment for salespeople
- ~~Outreach~~ — Sales email sequencing
- ~~HubSpot/Close/Attio~~ — Sales CRMs
- ~~ActiveCampaign/MailerLite~~ — Email marketing
- ~~Vibe Prospecting~~ — Lead generation for sales teams

---

## 5. NOTION CRM FOR JOB SEARCH (Already Connected!)

Since Notion is already connected, here's the database structure tailored for job searching:

### Database 1: Target Companies
| Property | Type | Options |
|----------|------|---------|
| Company Name | Title | |
| Stage | Select | Pre-Seed, Seed, Series A, B, C |
| Employees | Number | |
| AI-Native | Checkbox | |
| HQ | Text | |
| Source Portal | Multi-Select | YC, Wellfound, startup.jobs, etc. |
| Status | Select | Identified, Researching, Outreach Drafted, Connected, Applied, Interviewing, Offer, Rejected, Ghosted |
| Fit Score | Number | 1-10 |
| Notes | Rich Text | |

### Database 2: Contacts (Hiring Managers & Recruiters)
| Property | Type |
|----------|------|
| Name | Title |
| Company | Relation → Companies |
| Title | Text |
| LinkedIn Degree | Select (1st, 2nd, 3rd+) |
| Followers | Number |
| Connection Sent | Date |
| Response | Select (Pending, Accepted, No Response, Rejected) |
| Last Contacted | Date |
| Next Follow-Up | Date |
| Notes | Rich Text |

### Database 3: Applications
| Property | Type |
|----------|------|
| Role | Title |
| Company | Relation → Companies |
| Portal | Select (LinkedIn, Wellfound, YC, etc.) |
| Applied Date | Date |
| Salary Range | Text |
| Status | Select (Applied, Screen, Technical, Final, Offer, Rejected) |
| Hiring Manager | Relation → Contacts |

### Database 4: Daily Scan Log
| Property | Type |
|----------|------|
| Date | Title |
| Portals Scanned | Multi-Select |
| New Leads Found | Number |
| New Leads | Relation → Companies |
| Notes | Rich Text |

---

## 6. SCHEDULED TASKS

| Task | Cron | What It Does |
|------|------|-------------|
| **Daily Portal Scan** | `0 8 * * 1-5` (weekdays 8 AM) | Scan all 13 sources, extract new AI/ML roles, flag new listings |
| **Follow-Up Checker** | `0 9 * * 1-5` (weekdays 9 AM) | Check Notion CRM for overdue follow-ups, list who needs a message today |
| **Weekly Report** | `0 17 * * 5` (Friday 5 PM) | Generate weekly summary: applications sent, responses, interviews, pipeline health |
| **LinkedIn Engagement** | `0 10 * * 2,4` (Tue/Thu 10 AM) | Remind to comment on 3-5 posts from target hiring managers |

---

## 7. FULL PLUGIN/TOOL STACK — INSTALLATION ORDER

### Phase 1: Memory (Do First)
```
1. claude-mem plugin
   /plugin marketplace add thedotmack/claude-mem
   /plugin install claude-mem
   → Restart Claude Code

2. CLAUDE.md file (manual)
   → Create in outreach folder with campaign context
```

### Phase 2: Daily Scanning (Do This Week)
```
3. Schedule skill (already installed!)
   → Create "daily-portal-scan" scheduled task

4. Firecrawl plugin (optional, for heavy scraping)
   /plugin install firecrawl
   → Use when portals have complex JS rendering
```

### Phase 3: Tracking & Organization
```
5. Notion CRM databases (already connected!)
   → Build the 4 databases above

6. Gmail connector (when ready)
   → For email follow-ups alongside LinkedIn

7. Google Calendar connector
   → For interview scheduling
```

### Phase 4: Custom Skills (Build Over Time)
```
8. daily-portal-scanner skill (using skill-creator)
9. outreach-drafter skill
10. company-validator skill
11. hiring-manager-finder skill
12. application-tracker skill
```

---

## WHAT THIS STACK LOOKS LIKE IN ACTION

**Daily Workflow (8 AM):**
1. claude-mem auto-loads context from yesterday → you know where you left off
2. Scheduled portal scan runs → checks all 13 sources for new roles
3. New roles flagged → compared against existing target list
4. For each new match: company-validator skill → PASS/FAIL
5. For PASS companies: hiring-manager-finder skill → LinkedIn contact found
6. outreach-drafter skill → full outreach package generated
7. You review and send (human in the loop for actual sending)
8. application-tracker skill → logs everything to Notion CRM
9. Follow-up checker → alerts you on overdue follow-ups

**Weekly (Friday):**
- Weekly report auto-generates → pipeline health, response rates, next week's priorities

---

*Sources:*
- [claude-mem GitHub](https://github.com/thedotmack/claude-mem)
- [claude-mem npm](https://www.npmjs.com/package/claude-mem)
- [claude-mem docs](https://docs.claude-mem.ai/installation)
- [Firecrawl Claude Plugin](https://www.firecrawl.dev/blog/firecrawl-official-claude-plugin)
- [Claude Code Plugin Marketplace](https://code.claude.com/docs/en/discover-plugins)
- [Top Claude Code Plugins 2026](https://www.firecrawl.dev/blog/best-claude-code-plugins)
- [memsearch ccplugin](https://zilliztech.github.io/memsearch/claude-plugin/)
