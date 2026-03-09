# LinkedIn Job Scanner (MCP Playwright)

PRIMARY LinkedIn strategy: Uses MCP Playwright with logged-in session to search LinkedIn Jobs.

## Safety Limits (from Anti-Bot Intelligence Report)
- Max 5 result pages per scan (50 jobs)
- Random 3-7 second delays between page loads
- CAPTCHA/challenge detection → immediate stop
- Max 1 scan per day
- Use `browser_snapshot` (accessibility tree) for element targeting — NOT CSS selectors

## Search Flow

### Step 1: Navigate to LinkedIn Jobs Search
Use `browser_navigate` to go to:
```
https://www.linkedin.com/jobs/search/?keywords=AI%20Engineer&f_CS=B,C&f_TPR=r604800&sortBy=DD
```

Filters explained:
- `f_CS=B,C` → Company size 11-200 (B) and 201-500 (C) — targets startups
- `f_TPR=r604800` → Past week (7 days)
- `sortBy=DD` → Most recent first

### Step 2: Verify Login State
Use `browser_snapshot` to check the page. If you see a login form or "Sign in" prompt, STOP and report that the LinkedIn session has expired.

### Step 3: Extract Job Cards
Use `browser_snapshot` to get the accessibility tree. Look for job listing elements with:
- Job title (link text)
- Company name
- Location
- "Easy Apply" badge (SKIP these per outreach rules)
- "Top applicant" badge (PRIORITIZE these)

For each job card, extract:
```json
{
  "title": "AI Engineer",
  "company_name": "Example Corp",
  "location": "San Francisco, CA",
  "url": "https://www.linkedin.com/jobs/view/12345",
  "is_easy_apply": false,
  "is_top_applicant": true
}
```

### Step 4: Paginate (max 5 pages)
After extracting page 1, use `browser_snapshot` to find the "Next" pagination button.
- If found and current page < 5: click it with `browser_click`, wait 3-7 seconds, then extract next page
- If not found or page >= 5: stop pagination

Between each page load, wait a random 3-7 seconds.

### Step 5: CAPTCHA Detection
After each page load, check `browser_snapshot` for:
- "Let's do a quick security check"
- "Verify you're not a robot"
- CAPTCHA images or challenge text
- Any unusual verification prompts

If detected: IMMEDIATELY STOP the scan. Save whatever results you have so far.

### Step 6: Save Results
Save all extracted jobs as JSON to `data/mcp_scans/linkedin_<date>.json`:
```json
{
  "portal": "LinkedIn",
  "scan_date": "2026-03-09",
  "total_pages_scanned": 3,
  "results": [
    {
      "title": "AI Engineer",
      "company_name": "Example Corp",
      "location": "San Francisco, CA",
      "url": "https://www.linkedin.com/jobs/view/12345",
      "is_easy_apply": false,
      "is_top_applicant": true,
      "salary_range": "",
      "work_model": "remote"
    }
  ]
}
```

### Step 7: Persist to Database
Run: `python -m src.cli.main mcp-persist linkedin data/mcp_scans/linkedin_<date>.json`

### Additional Keywords (run as separate searches if time permits)
After the first search for "AI Engineer", optionally repeat Steps 1-6 for:
- "ML Engineer" (f_CS=B,C)
- "LLM Engineer" (f_CS=B,C)
- "founding engineer AI" (f_CS=B,C)

Space each keyword search by at least 30 seconds.

## Post-Scan Filtering
After collecting all results:
1. Remove any with `is_easy_apply: true`
2. Highlight any with `is_top_applicant: true` (prioritize these)
3. Check company size < 1000 employees
4. Flag companies with H1B sponsorship status if visible

## Output Summary
Print a summary table:
| Metric | Count |
|--------|-------|
| Pages scanned | X |
| Total jobs found | X |
| Easy Apply (skipped) | X |
| Top Applicant | X |
| New (not in DB) | X |
