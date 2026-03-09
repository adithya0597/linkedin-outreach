# JobBoard AI Scanner (MCP Playwright Probe)

PRIMARY scanner for JobBoard AI — uses MCP Playwright to probe.
Previously demoted (zero listings). This skill checks current state.

## Search Flow

### Step 1: Navigate
Use `browser_navigate` to: `https://jobboardai.io/jobs?search=AI+Engineer`

### Step 2: Check Page State
Use `browser_snapshot` to verify:
- Job listings exist on the page
- Site is functional (not 404/500)

### Step 3: Extract (if results exist)
If job listings found: extract title, company, location, URL.
Save to `data/mcp_scans/jobboard_ai_<date>.json`
Run: `python -m src.cli.main mcp-persist jobboard_ai data/mcp_scans/jobboard_ai_<date>.json`

### Step 4: Report
If 0 results: Report "JobBoard AI still returning zero listings — keep demoted"
If results found: Report count and recommend re-enabling in registry
