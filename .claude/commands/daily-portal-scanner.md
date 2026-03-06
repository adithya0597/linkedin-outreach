---
name: daily-portal-scanner
description: "**Daily Job Portal Scanner**: Scans 13 job sources (12 AI/ML job portals + LinkedIn) with three-tier H1B filtering for new roles matching startup criteria (under 1000 employees, Seed-Series C, AI-native, US HQ). Uses tiered H1B rules: startup portals = no filter, general portals + LinkedIn = cross-check Frog Hire/H1BGrader/MyVisaJobs, include unless explicitly no sponsorship. Use this skill whenever the user mentions scanning portals, checking job boards, finding new jobs, daily scan, job search update, new listings, portal check, or wants to discover fresh AI/ML engineering roles. Also trigger when the user says things like 'any new jobs today', 'check for openings', 'scan for roles', or 'what's new on the job boards'. This is the primary job discovery tool — use it proactively when the user starts a new session and hasn't scanned recently."
---

# Daily Portal Scanner

Scan 13 job sources (12 portals + LinkedIn) for new AI/ML engineer roles using three-tier H1B filtering. Compare against the existing target list to flag new opportunities.

## Context

You are scanning job portals for Bala Adithya Malaraju, an AI Engineer on an F1 student visa who REQUIRES H1B sponsorship. He specializes in Graph RAG, Enterprise LLM pipelines, healthcare data, and mainframe-to-cloud migration. The goal is to find AI-native startups that match strict criteria. H1B filtering follows a **three-tier system** — not all portals are filtered the same way.

## Target Criteria (ALL must pass — except H1B which is tiered)

- **Employees:** <1,000
- **Funding:** Seed through Series C
- **Product:** AI/ML as CORE product (not just "uses AI")
- **Location:** USA headquarters ONLY
- **H1B Sponsorship:** **TIERED** — see below
- **Disqualified:** FAANG, Big Tech, consulting/staffing firms, non-US companies, companies that explicitly won't sponsor H1B

## THREE-TIER H1B FILTERING SYSTEM (CRITICAL)

### Tier 3 — Startup-Specific Portals: **NO H1B filter**
Add ALL companies matching profile. Do NOT cross-check H1B.
- workatastartup.com (YC), wellfound.com, startup.jobs, hiring.cafe, topstartups.io

### Tier 2 — General Job Portals: **H1B cross-check required**
Cross-check each company: Frog Hire → H1BGrader → MyVisaJobs. Include UNLESS explicit "no sponsorship." No data = still include.
- froghire.com ⭐ (scan first), jobboardai.io, aijobs.ai, welcometothejungle.com, builtin.com, trueup.io, jobright.ai

### Tier 1 — LinkedIn: **H1B cross-check required** (same as Tier 2)
- First run: last 7 days only. Subsequent: newly posted since last scan.

### H1B Verification Source Priority (Tier 1 & 2 only)
1. **Frog Hire** (froghire.ai) — PRIMARY at https://www.froghire.ai/company?search=COMPANY_NAME
2. H1BGrader / MyVisaJobs — Secondary, only if Frog Hire has no data
3. No data = still include. Mark "Unknown."

## Scanning Cadence
- **First run:** LinkedIn = last 7 days. All other portals = ALL current listings.
- **Subsequent runs:** ALL 13 sources = only newly posted since last scan.

## Dual-Scan Schedule

### 8:00 AM — Full Scan (all 13 sources)
All 12 portals + LinkedIn. Comprehensive sweep.

### 2:00–3:00 PM — Afternoon Rescan (9 sources, new listings only)
Wellfound, YC Work at a Startup, Frog Hire, LinkedIn, Built In, TrueUp, Jobright AI, AI Jobs, JobBoard AI.

### Morning-Only (4 sources)
startup.jobs, Hiring Cafe, Top Startups, Welcome to the Jungle — lower posting velocity.

### Frequency Review
Assignments are data-driven via Portal_Analytics.md. Score each portal weekly (0–12). Promote at 4+ points for 2 weeks. Demote below 3 for 2 weeks.

## Search Keywords
Primary: "AI Engineer", "ML Engineer", "LLM Engineer"
Secondary: "RAG", "Knowledge Graph", "NLP Engineer", "GenAI Engineer"
Location: United States / Remote (US)

## Scan Steps

For each portal:
1. **Identify tier** → determines H1B rules
2. **Open and search** using primary keywords + filters
3. **Extract** for each role: Company, role title, salary, location, posting date, URL, employee count, H1B status
4. **Apply H1B filter by tier:**
   - Tier 3: Skip H1B check. Mark "N/A — startup portal"
   - Tier 2: Cross-check Frog Hire → H1BGrader → MyVisaJobs. Include unless explicit "no sponsorship"
   - Tier 1: Same as Tier 2
5. **Validate** remaining criteria (employees, funding, AI-native, US HQ)
6. **Compare** against `/mnt/lineked outreach/Startup_Target_List.md` — flag NEW
7. **Log** portal health and results
8. **Collect analytics** per portal: total listings, new count, AM/PM timestamps, pass rate, duplicates, disappeared listings, scan duration (minutes)

## Output

Create `/mnt/lineked outreach/Daily_Scan_[YYYY-MM-DD].md` with scan summary, new leads table (including tier and H1B status), portal status, H1B verification log, and actions needed.

Update `Startup_Target_List.md`, Notion CRM, and `Portal_Analytics.md` (per-portal metrics + duplicate tracking).

## Edge Cases
- Portal down: note and move on
- CAPTCHA: skip, note for user
- Ambiguous company size: mark "Needs Validation"
- Duplicates: note first portal, don't double-count
- No H1B data (Tier 1/2): still include, mark "⚠️ Unknown"
- Explicit "no sponsorship" (Tier 1/2): exclude, mark "❌ Explicit No"
