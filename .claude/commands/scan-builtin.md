# Built In Scanner (MCP Playwright Probe)

PRIMARY scanner for Built In — uses MCP Playwright to probe and scrape.
Built In was previously demoted (zero startup matches). This skill probes the current state.

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://builtin.com/jobs/ai-ml?search=AI+Engineer`

### Step 2: Check Page State
Use `browser_snapshot` to verify:
- Job listings are visible
- No paywall or login requirement
- Content has loaded (not a blank/spinner page)

### Step 3: Filter for Startups
If the page has company size filters, apply: 1-50, 51-200, 201-500 employees.
If not, manually skip large companies (1000+ employees) during extraction.

### Step 4: Extract Job Listings
From accessibility tree, extract: title, company, location, URL, salary, work model.

### Step 5: Evaluate Results
If 0 results found:
- Report "Built In still returning zero startup matches"
- Recommend keeping portal demoted

If results found:
- Save to `data/mcp_scans/builtin_<date>.json`
- Run: `python -m src.cli.main mcp-persist builtin data/mcp_scans/builtin_<date>.json`
