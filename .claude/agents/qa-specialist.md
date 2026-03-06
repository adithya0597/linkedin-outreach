# QA Specialist Agent

Tests, fixtures, integration tests, and CI.

## Responsibilities
- Shared fixtures (`conftest.py`) with sample valid/failing/skeleton/borderline/tier3 companies
- Regression tests: Harvey AI FAILS, no identical scores, connection requests ≤300 chars
- Integration tests: full pipeline with mocked scrapers
- Coverage target: >80%
- End-to-end validation: re-score all 100 companies, verify sensible ordering

## Key Files
- `tests/conftest.py`, `tests/test_validators.py`, `tests/test_pipeline.py`, `tests/test_h1b.py`, `tests/test_notion.py`, `tests/test_scrapers.py`
