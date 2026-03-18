---
name: company-validator
description: "**Startup Company Validator**: Validates whether a company meets strict AI startup targeting criteria — checks employee count (under 1000), funding stage (Seed-Series C), AI-native product, US HQ, and H1B sponsorship (tiered based on source portal). Use this skill whenever the user says 'validate [company]', 'is this a fit', 'check startup', 'does [company] qualify', 'is [company] worth targeting', or anytime a new company is discovered from a portal scan or LinkedIn and needs qualification. Also trigger when building the target list or when the user asks 'should I apply to [company]'. This is a fast, decisive tool — PASS or FAIL with evidence."
---

# Company Validator

Quickly validate whether a company meets the targeting criteria for your AI startup job search.

## Target Criteria (ALL must pass)

| # | Criterion | Requirement | How to Check |
|---|-----------|-------------|--------------|
| 1 | **Employee Count** | < 1,000 | LinkedIn company page, Crunchbase, or job portal listing |
| 2 | **Funding Stage** | Seed through Series C | Crunchbase, PitchBook, or company "About" page |
| 3 | **AI-Native Product** | AI/ML is the CORE product, not a feature | Company website, product page, or YC listing |
| 4 | **US Headquarters** | USA-based HQ | LinkedIn company page or website footer |
| 5 | **H1B Sponsorship** | **TIERED** — depends on source portal | Frog Hire (primary), H1BGrader, MyVisaJobs |
| 6 | **Not Disqualified** | Not FAANG, Big Tech, consulting, staffing, or non-US | Common sense + quick check |

## THREE-TIER H1B FILTERING

- **Tier 3 (Startup portals — YC, Wellfound, startup.jobs, Hiring Cafe, topstartups.io):** NO H1B check. Auto-PASS.
- **Tier 2 (General portals — Frog Hire, jobboardai, aijobs, WTTJ, builtin, trueup, jobright):** Cross-check: Frog Hire (primary) → H1BGrader/MyVisaJobs (secondary). Include UNLESS explicit "no sponsorship." No data = still include.
- **Tier 1 (LinkedIn):** Same as Tier 2.

### H1B Verification Source Priority (Tier 1 & 2 only)
1. **Frog Hire** (froghire.ai) — PRIMARY at https://www.froghire.ai/company?search=COMPANY_NAME
2. H1BGrader / MyVisaJobs — Secondary, only if Frog Hire has no data
3. No data = still include. Mark "⚠️ Unknown."

## Automatic Disqualifiers
- FAANG, Big Tech, consulting/staffing firms, non-US HQ
- Series D+ or public companies
- Core product isn't AI
- **Explicit "no H1B sponsorship" or "US citizens only"** (Tier 1/2 only)

## Output Format

```markdown
# Company Validation: [Company Name]
## VERDICT: ✅ PASS / ❌ FAIL
## Source Portal: [portal] — Tier [1/2/3]

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Employees < 1,000 | ✅/❌ | [evidence] |
| Seed–Series C | ✅/❌ | [evidence] |
| AI-Native Product | ✅/❌ | [evidence] |
| US HQ | ✅/❌ | [evidence] |
| H1B Sponsorship | ✅/⚠️/❌/N/A | [source + tier] |
| Not Disqualified | ✅/❌ | [evidence] |

## Fit Score: [1-10]
## Recommended Action: [next steps]
```
