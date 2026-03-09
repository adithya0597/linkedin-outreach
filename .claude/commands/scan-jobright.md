# Jobright Scanner (MCP Playwright Backup)

BACKUP scanner for Jobright AI — use only if the primary Patchright scraper fails.

Primary: `python -m src.cli.main scan --portal jobright`

## When to Use This Backup
- Patchright scraper is blocked or failing
- Jobright has upgraded anti-bot beyond Patchright's capabilities

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://jobright.ai/jobs?searchKeyword=AI%20Engineer&location=United+States`

### Step 2: Wait for Load
Wait 3-5 seconds for dynamic content to render.
Use `browser_snapshot` to check for job listings.

### Step 3: Check for Blocks
If the snapshot shows CAPTCHA, verification challenge, or "Access Denied":
- STOP immediately
- Report the block type

### Step 4: Extract Job Cards
Look for job listing elements. Use accessibility tree roles (links, headings) not CSS classes.
Extract: title, company, location, URL, salary (if visible).

### Step 5: Save and Persist
Save to `data/mcp_scans/jobright_<date>.json`
Run: `python -m src.cli.main mcp-persist jobright data/mcp_scans/jobright_<date>.json`
