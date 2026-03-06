# H1B Automation Agent

Automated H1B verification via 3-source waterfall.

## Responsibilities
- `H1BVerifier` orchestrating FrogHire → H1BGrader → MyVisaJobs
- `FrogHireClient` (Playwright-based), `H1BGraderClient` (httpx), `MyVisaJobsClient` (httpx)
- Tier-aware logic: Tier 3 = auto-pass (zero HTTP), Tier 1/2 = waterfall
- `batch_verify()` with rate limiting and DB persistence
- Extracts: H1B status, PERM, E-Verify, LCA count, approval rate

## Key Files
- `src/validators/h1b_verifier.py`
