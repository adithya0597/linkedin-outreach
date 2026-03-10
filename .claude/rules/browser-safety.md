## Browser Safety Rules

### NEVER Launch Real Browsers in Tests
- All tests run with `autouse` conftest fixture that blocks Playwright/Patchright
- If a test needs a real browser, mark it `@pytest.mark.live` (excluded by default)
- When writing scraper tests, ALWAYS mock `_launch()` and `_close()` on the scraper instance
- NEVER patch playwright at the module level inside individual tests — the conftest handles it

### Playwright channel="chrome" Is MANDATORY
- Every `chromium.launch()` and `chromium.launch_persistent_context()` call MUST include `channel="chrome"`
- Without `channel="chrome"`, Playwright uses its bundled Chromium (~400MB) which has NO logged-in sessions
- The user's Chrome at `/Applications/Google Chrome.app` has all portal sessions logged in
- This is enforced by pre-commit hook — commits without it will be rejected

### Worktree Agent Rules
- Before running `pytest` in a worktree, verify that `tests/conftest.py` contains `_block_browser_launch`
- If the conftest is missing the guard, copy from main: `git show main:tests/conftest.py > tests/conftest.py`
- NEVER run `pytest` in a worktree without confirming browser mocking is in place
- Prefer `PLAYWRIGHT_BROWSERS_PATH=/dev/null pytest` as a failsafe

### Testing Scrapers
- Use `patch.object(scraper, "_launch", new_callable=AsyncMock)` to mock browser launch
- Use `patch.object(scraper, "_close", new_callable=AsyncMock)` to mock cleanup
- Use `patch.object(scraper, "_new_page_with_behavior", ...)` to mock page creation
- See `tests/test_patchright.py` for the canonical pattern
