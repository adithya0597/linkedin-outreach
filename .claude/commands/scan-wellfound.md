# Wellfound Scanner (MCP Playwright Backup)

BACKUP scanner for Wellfound — use only if the primary `__NEXT_DATA__` httpx scraper fails.

Primary: `python -m src.cli.main scan --portal wellfound`

## When to Use This Backup
- The httpx `__NEXT_DATA__` parser returns 0 results
- Wellfound has changed their page structure
- Cloudflare is blocking httpx requests

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://wellfound.com/role/ai-engineer`

### Step 2: Verify Page Loaded
Use `browser_snapshot` to check the accessibility tree for job listings.

### Step 3: Extract Job Cards
Look for job listing elements with:
- Job title
- Company name
- Location
- Salary range (if visible)
- Work model (Remote/Hybrid/Onsite)

Extract as JSON:
```json
{
  "title": "AI Engineer",
  "company_name": "Startup Inc",
  "location": "San Francisco, CA (Remote)",
  "url": "https://wellfound.com/jobs/12345",
  "salary_range": "$150k-$200k",
  "work_model": "remote"
}
```

### Step 4: Save and Persist
Save to `data/mcp_scans/wellfound_<date>.json`
Run: `python -m src.cli.main mcp-persist wellfound data/mcp_scans/wellfound_<date>.json`
