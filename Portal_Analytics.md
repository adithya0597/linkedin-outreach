# Portal Analytics — Scan Frequency Decision Engine

> **Purpose:** Track per-portal performance metrics to make data-driven decisions about which portals need 2x/day scanning and which are fine with 1x/day.
> **Updated after:** Every daily scan (automated via daily-portal-scanner skill)

---

## Decision Framework

A portal earns a 2x/day scan if it scores **4+ points** on this rubric:

| Metric | Threshold for +1 Point | Threshold for +2 Points |
|--------|----------------------|------------------------|
| **Posting Velocity** | 3+ new listings/day avg | 8+ new listings/day avg |
| **Afternoon Post Rate** | 20%+ of posts appear after 12 PM | 40%+ appear after 12 PM |
| **Lead Conversion** | 15%+ of listings pass validation | 30%+ pass validation |
| **Exclusive Listings** | 30%+ not found on other portals | 60%+ exclusive |
| **Time-to-Fill Speed** | 30%+ listings gone within 3 days | 50%+ gone within 3 days |
| **Outreach Response Rate** | 15%+ response from this portal's leads | 25%+ response rate |

**Score interpretation:**
- **0–2 points:** 1x/day is sufficient (morning only)
- **3 points:** Borderline — consider 2x/day if capacity allows
- **4+ points:** 2x/day recommended
- **6+ points:** High-priority — scan first in every cycle

---

## Current Scan Frequency Assignments

> Update this table after accumulating 2+ weeks of data. Until then, use the initial assignments based on portal characteristics.

| Portal | Tier | Current Frequency | Score | Leads (03/05) | Last Evaluated |
|--------|------|:-----------------:|:-----:|:-------------:|:--------------:|
| **Jobright AI** ⭐ | 2 | 2x/day | ~6 | **11+1** | 03/05 — HIGHEST YIELD |
| **Hiring Cafe** | 3 | 2x/day ↑ | ~5 | **~16** | 03/05 — Promoted! High volume |
| **TrueUp** | 2 | 2x/day | ~4 | **5+2** | 03/05 — Good filters |
| **Work at a Startup (YC)** | 3 | 2x/day | ~4 | **4+4** | 03/05 — Fresh YC batches |
| **Top Startups** | 3 | 1x/day | ~3 | **4** | 03/05 — Lower volume, good quality |
| **Wellfound** | 3 | 2x/day | — | ⚠️ BLOCKED | 03/05 — Password wall, can't rescan |
| **startup.jobs** | 3 | 1x/day | ~2 | **1+3** | 03/05 — Mixed quality, many non-US |
| **LinkedIn** | 1 | 1x/day ↓ | ~2 | **1** | 03/05 — Simplify extension interference, few startups |
| **Frog Hire** ⭐ | — | As needed | N/A | N/A | 03/05 — **Reclassified as H1B verification tool** |
| **JobBoard AI** | 2 | 1x/day ↓ | 0 | **0** | 03/05 — Demoted! Zero listings |
| **Welcome to the Jungle** | 2 | 1x/day | 0 | **0** | 03/05 — Demoted! No startups, all large corps |
| **AI Jobs** | 2 | 1x/day ↓ | ~1 | **1** (cross-confirm) | 03/05 — AssemblyAI only. All large companies. Low startup volume |
| **Built In** | 2 | 1x/day ↓ | 0 | **0** | 03/05 — Demoted! Capital One 10+ listings, all large enterprises. Zero startups |

---

## Per-Portal Metrics (Cumulative)

> Updated after each scan. Each portal has its own tracking block.

### Work at a Startup (YC) — Tier 3

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Wellfound (AngelList) — Tier 3

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### startup.jobs — Tier 3

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Hiring Cafe — Tier 3

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Top Startups — Tier 3

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Frog Hire ⭐ — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### JobBoard AI — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### AI Jobs — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Welcome to the Jungle — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Built In — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### TrueUp — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### Jobright AI — Tier 2

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

### LinkedIn — Tier 1

| Week | Total Listings | New/Day Avg | AM Posts | PM Posts | PM % | Passed Validation | Pass % | Exclusive % | Gone <3 Days | Response Rate |
|------|:-----------:|:-----------:|:--------:|:--------:|:----:|:-----------------:|:------:|:-----------:|:------------:|:-------------:|
| — | — | — | — | — | — | — | — | — | — | — |

**Running Score:** — / 12 | **Recommendation:** —

---

## Cross-Portal Duplicate Analysis

> Track how often the same listing appears on multiple portals. High overlap = one scan is enough for the duplicate source.

| Company + Role | Found On (portals) | First Seen On | First Seen Time |
|----------------|-------------------|:-------------:|:---------------:|
| Pair Team — AI Engineer | Wellfound, startup.jobs, YC | Wellfound | 03/04 |
| Fieldguide — AI Engineer | Top Startups, startup.jobs | Top Startups | 03/05 |
| Hex — AI/ML Engineer | Hiring Cafe, Jobright AI | Hiring Cafe | 03/05 |
| Inworld AI — AI Engineer | TrueUp, Jobright AI | TrueUp | 03/05 |
| Hippocratic AI — AI Engineer | Jobright AI (confirmed existing) | Original research | 03/04 |
| Clicks (YC F25) — Software Eng | YC (scan + rescan) | YC | 03/04 |
| AssemblyAI — Applied AI Eng | Top Startups, AI Jobs | Top Startups | 03/05 |

**Overlap Summary (update weekly):**

| Portal | Total Listings (week) | Also Found Elsewhere | Exclusive | Exclusive % |
|--------|:--------------------:|:--------------------:|:---------:|:-----------:|
| — | — | — | — | — |

---

## Posting Time Distribution (AM vs PM)

> For each scan, note when listings were posted. If a portal shows heavy PM posting patterns, that's a strong signal for 2x/day scanning.

**How to collect:** During each scan, check the "posted" timestamp on listings. Classify as:
- **AM:** Posted between 12:00 AM and 11:59 AM (any timezone shown)
- **PM:** Posted between 12:00 PM and 11:59 PM

**If the portal doesn't show timestamps:** Mark as "No timestamp" — track the delta between morning and afternoon scans instead (i.e., count how many NEW listings appear in the afternoon scan that weren't in the morning scan).

---

## Time-to-Fill Tracker

> Sample check: re-visit 10 listings from 3 days ago on each portal. How many are still live?

| Portal | Check Date | Listings Sampled | Still Live | Gone | Gone % | Avg Days to Fill |
|--------|:----------:|:---------------:|:----------:|:----:|:------:|:----------------:|
| — | — | — | — | — | — | — |

**Interpretation:**
- **>50% gone in 3 days:** High urgency portal — 2x/day strongly recommended
- **30–50% gone in 3 days:** Moderate urgency — 2x/day if capacity allows
- **<30% gone in 3 days:** Low urgency — 1x/day is fine

---

## Weekly Scan Frequency Review

> Every Friday, as part of the Weekly Pipeline Review (Prompt 7), run this evaluation.

### Review Steps

1. **Update all per-portal metric tables** with the current week's data
2. **Score each portal** using the 6-metric rubric (0–12 scale)
3. **Compare scores to current frequency assignment** — promote or demote portals
4. **Check cross-portal duplicates** — if a portal's listings are 70%+ duplicated elsewhere, drop to 1x/day regardless of score
5. **Update the "Current Scan Frequency Assignments" table** at the top
6. **Update the scanner skill and scheduled task** if any portals change frequency

### Promotion/Demotion Rules

| Action | Trigger |
|--------|---------|
| **Promote to 2x/day** | Score reaches 4+ for 2 consecutive weeks |
| **Demote to 1x/day** | Score drops below 3 for 2 consecutive weeks |
| **Emergency promote** | Time-to-fill is <2 days (listings vanish fast) |
| **Emergency demote** | Portal down 3+ days, or 0 new listings for a full week |

---

## ROI by Portal (Monthly Summary)

> Which portals are actually producing results? Track the full funnel from listing → application → interview → offer.

| Portal | Listings Found | Passed Validation | Outreach Sent | Responses | Interviews | Cost (time in min) | ROI Score |
|--------|:-------------:|:-----------------:|:-------------:|:---------:|:----------:|:-----------------:|:---------:|
| — | — | — | — | — | — | — | — |

**ROI Score formula:** `(Interviews × 10 + Responses × 3 + Validated × 1) ÷ Time Spent (min)`

Higher = more efficient. Use this to cut portals that eat time but produce nothing.

---

## Data Collection Checklist (Per Scan)

After every scan, log these data points to keep analytics current:

- [ ] Total listings count per portal
- [ ] New listings count (not seen in previous scan)
- [ ] Posting timestamps (AM/PM) where available
- [ ] For afternoon scans: count of listings NOT seen in the morning scan
- [ ] Validation pass/fail counts for new listings
- [ ] Note any listings also found on other portals (duplicates)
- [ ] Note any listings that disappeared since last scan (time-to-fill signal)
- [ ] Log scan duration per portal (for ROI calculation)
