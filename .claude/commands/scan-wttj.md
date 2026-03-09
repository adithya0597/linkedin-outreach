# Welcome to the Jungle Scanner (MCP Playwright Backup)

BACKUP scanner for WTTJ — use only if the primary Algolia API scraper fails.

Primary: `python -m src.cli.main scan --portal wttj`

## When to Use This Backup
- Algolia API keys have changed and extractor can't find new ones
- WTTJ has removed Algolia integration
- API returns errors

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://www.welcometothejungle.com/en/jobs?query=AI+Engineer&refinementList%5Boffices.country_code%5D%5B%5D=US`

### Step 2: Wait for Content
Wait 3-5 seconds. Use `browser_snapshot` to check for job listings.

### Step 3: Extract Job Listings
From accessibility tree: title, company, location, URL, salary, work model, contract type.

### Step 4: Save and Persist
Save to `data/mcp_scans/wttj_<date>.json`
Run: `python -m src.cli.main mcp-persist wttj data/mcp_scans/wttj_<date>.json`
