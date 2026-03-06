# Daily Portal Scan — Scheduled Task Configuration

## TWO SCHEDULED TASKS

### Task 1: `daily-portal-scan-morning`
**Cron:** `0 8 * * 1-5` (Weekdays at 8:00 AM local time)
**Scope:** All 13 sources (full scan)

### Task 2: `daily-portal-scan-afternoon`
**Cron:** `0 14 * * 1-5` (Weekdays at 2:00 PM local time)
**Scope:** 9 high-velocity sources only (new listings since morning scan)

## Setup Instructions
Run this in **Claude Code** (not Cowork):
```
/schedule
```
Then paste the prompt below when asked for the task description.

---

## Task Prompt (copy this entire block):

```
Scan 13 job sources (12 portals + LinkedIn) for new AI/ML engineer roles matching Bala Adithya Malaraju's target criteria. Use the THREE-TIER H1B FILTERING system. Compare against existing targets and log results.

## TARGET CRITERIA (all must pass — except H1B which is tiered)
- <1,000 employees
- Seed through Series C funding
- AI/ML as CORE product (not just "uses AI")
- USA headquarters ONLY
- H1B: THREE-TIER system (see below)
- DISQUALIFIED: FAANG, Big Tech, consulting/staffing firms, non-US companies, companies that explicitly won't sponsor H1B

## THREE-TIER H1B FILTERING (CRITICAL — follow exactly)

### Tier 3 — Startup-Specific Portals: NO H1B filter
Add ALL companies matching profile. Do NOT cross-check H1B status.
- workatastartup.com (YC)
- wellfound.com (AngelList)
- startup.jobs
- hiring.cafe
- topstartups.io

### Tier 2 — General Job Portals: H1B cross-check required
Cross-check each company on Frog Hire → H1BGrader → MyVisaJobs.
Include UNLESS company explicitly says "no sponsorship" or "US citizens only."
If no H1B data found, still include — mark as "Unknown."
- froghire.com (scan first — all listings sponsor H1B)
- jobboardai.io
- aijobs.ai
- app.welcometothejungle.com
- builtin.com
- trueup.io
- jobright.ai

### Tier 1 — LinkedIn: H1B cross-check required (same as Tier 2) — **PREMIUM FEATURES ENABLED**
- First run: scan jobs posted in last 7 days only
- Subsequent runs: only newly posted since last scan

#### LINKEDIN PREMIUM SCAN (MANDATORY — run on every scan)
Adithya has LinkedIn Premium. Run these Premium-specific steps on EVERY scan:

**Step P1: "Top Applicant" Collection Scan**
- Navigate to: https://www.linkedin.com/jobs/collections/top-applicant/
- Search with keywords: `AI engineer`, `ML engineer`, `LLM engineer`
- SKIP all "Easy Apply" listings
- SKIP pure "Data Engineer" roles without AI component
- PRIORITIZE jobs showing "You'd be a top applicant" badge
- Check Applicant Insights (how Adithya ranks vs other applicants)

**Step P2: "Top US Startups" Collection Scan**
- Navigate to: https://www.linkedin.com/jobs/collections/top-startups/?keywords=AI%20engineer
- This returns ONLY LinkedIn-verified top startups — best LinkedIn source for startup roles
- Scan all results, apply standard criteria (employees, funding, AI-native)

**Step P3: "Top Choice Jobs" — Mark Best-Fit Roles**
- When applying to roles with fit score ≥8, mark as "Top Choice"
- This signals strong interest to the recruiter — increases visibility vs other applicants
- Reserve for Tier 1-2 companies only (don't overuse)
- Log which jobs were marked as Top Choice in the scan report

**Step P4: "Actively Hiring" Filter**
- Use the "Actively Hiring" filter when browsing job search
- Surfaces companies actively reviewing applications RIGHT NOW
- Combine with keywords: `AI engineer`, `ML engineer`, `founding engineer`
- These jobs have faster response cycles — apply + outreach immediately

**Step P5: "Who Viewed Your Profile" Check**
- Navigate to: https://www.linkedin.com/me/profile-views/
- Premium shows FULL 90-day viewer history
- Flag ANY viewer from a target company or AI startup → WARM LEAD
- For warm leads: trigger immediate InMail or connection request
- Log all relevant profile viewers in the scan report

**Step P6: InMail Credit Check**
- Note remaining InMail credits for the month
- If warm leads found in P5, send InMail immediately (highest priority use of credits)
- Check for "Open Profile" on all 3rd+ degree targets → FREE InMail (no credit cost)
- Log InMail usage and remaining credits in the report

**Step P7: "Company Insights" — Target Company Research**
- Use LinkedIn Premium Company Insights for exclusive data on target companies
- Check employee growth rate, hiring trends, department breakdowns
- Supplements Crunchbase/web research in Agent 1
- Flag companies with rapid AI/engineering team growth

**Step P8: "Unlimited People Browsing" — Contact Discovery**
- Run unlimited People searches for hiring managers and recruiters
- No monthly search cap — search freely without limits
- Use advanced filters: location, company, keywords

### H1B Verification Source Priority (Tier 1 & 2 only)
1. Frog Hire (froghire.ai) — PRIMARY. Search at https://www.froghire.ai/company?search=COMPANY_NAME
2. H1BGrader (h1bgrader.com) — Secondary, only if Frog Hire has no data
3. MyVisaJobs (myvisajobs.com) — Secondary, only if Frog Hire has no data

## SCANNING CADENCE
- First run: LinkedIn = last 7 days. All other portals = ALL current listings.
- Subsequent runs: ALL 13 sources = only newly posted since last scan.

## DUAL-SCAN SCHEDULE
### Morning Scan (8 AM): All 13 sources — full sweep
### Afternoon Scan (2 PM): 9 sources — new listings only since morning
Afternoon portals: Wellfound, YC Work at a Startup, Frog Hire, LinkedIn, Built In, TrueUp, Jobright AI, AI Jobs, JobBoard AI
Morning-only portals: startup.jobs, Hiring Cafe, Top Startups, Welcome to the Jungle

## SEARCH KEYWORDS
Primary: "AI Engineer", "ML Engineer", "LLM Engineer"
Secondary: "RAG", "Knowledge Graph", "NLP Engineer", "GenAI Engineer"
Location: United States / Remote (US)

## FOR EACH PORTAL:
1. Identify the portal's tier (1, 2, or 3)
2. Search using primary keywords
3. Extract: Company name, role title, salary range (if shown), location, posting date, portal URL
4. Apply H1B filter based on tier:
   - Tier 3: Skip H1B check. Mark "N/A — startup portal"
   - Tier 2: Cross-check Frog Hire → H1BGrader → MyVisaJobs. Include unless explicit "no sponsorship"
   - Tier 1: Same as Tier 2
5. Quick-validate remaining criteria (employee count, AI-native, US HQ)
6. Check if company already exists in /mnt/lineked outreach/Startup_Target_List.md
7. Collect analytics per portal: total listings, new count, AM/PM timestamps, pass rate, duplicates, disappeared listings, scan duration

## OUTPUT:
1. Create /mnt/lineked outreach/Daily_Scan_[YYYY-MM-DD].md with:
   - Date and sources scanned (X/13)
   - NEW roles not in existing target list (with all extracted details + H1B status + tier)
   - UPDATED roles (salary changes, new openings at known companies)
   - H1B verification log for Tier 1/2 companies
   - Summary stats: sources scanned, new leads found, total active listings

2. Update /mnt/lineked outreach/Startup_Target_List.md:
   - Add new qualifying companies to TIER 4: PORTAL-SOURCED LEADS
   - Update JOB SOURCES TO SCAN table with scan dates

3. Update Notion "Daily Portal Scan Log" database:
   - Log scan date, portals scanned, new leads count, new company names, actions taken

4. Update /mnt/lineked outreach/Portal_Analytics.md:
   - Per-portal metrics (listings, new count, AM/PM split, pass rate, duplicates, disappeared, scan duration)
   - For afternoon scans: count NEW listings not in morning scan (core metric for 2x/day value)
   - On Fridays: run frequency review — score each portal (0–12) and update assignments

## SUCCESS CRITERIA:
- All 13 sources attempted (note any that are down/blocked)
- Every new lead has: company name, role, salary range, location, portal link, H1B status, source tier
- H1B cross-check completed for all Tier 1/2 companies (Frog Hire first, then secondary if needed)
- Tier 3 companies included without H1B check
- No duplicates added to target list
- Notion scan log updated
- **LinkedIn Premium steps completed:** Top Applicant scanned, Top US Startups scanned, Top Choice marked on best-fit jobs, Actively Hiring filter used, Profile Viewers checked, Company Insights checked, InMail credits logged
- **Any profile viewers from target companies flagged as warm leads**
- **Top Choice reserved for fit score ≥8 only (Tier 1-2 companies)**
```

---

## After Setup
Two tasks run automatically on weekdays:
- **8:00 AM** — Full scan of all 13 sources
- **2:00 PM** — Afternoon rescan of 9 high-velocity sources (new listings only)

Trigger either manually anytime with:
```
/run daily-portal-scan-morning
/run daily-portal-scan-afternoon
```
