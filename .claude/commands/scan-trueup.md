# TrueUp Scanner (MCP Playwright Backup)

BACKUP scanner for TrueUp — use only if the primary Patchright scraper fails.

Primary: `python -m src.cli.main scan --portal trueup`

## When to Use This Backup
- Patchright scraper returns 403 or is blocked
- TrueUp has upgraded anti-bot protection

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://www.trueup.io/jobs?title=AI%20Engineer&location=United+States`

### Step 2: Wait and Check
Wait 3-5 seconds. Use `browser_snapshot` to verify content loaded.
If blocked (403, CAPTCHA): STOP and report.

### Step 3: Extract Job Listings
Use accessibility tree to find job rows/cards. Extract: title, company, location, URL, salary.

### Step 4: Save and Persist
Save to `data/mcp_scans/trueup_<date>.json`
Run: `python -m src.cli.main mcp-persist trueup data/mcp_scans/trueup_<date>.json`
