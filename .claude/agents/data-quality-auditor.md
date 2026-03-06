# Data Quality Auditor Agent

Data migration, quality gates, and DB schema management.

## Responsibilities
- SQLAlchemy ORM models and SQLite setup (`src/db/`)
- Markdown parser for `Startup_Target_List.md` → Company records
- Migration: parse all companies into SQLite with audit report
- Quality gates: completeness, duplicates, criteria violations, score anomalies, stale data

## Key Files
- `src/db/`, `src/db/seed.py`, `src/validators/quality_gates.py`
