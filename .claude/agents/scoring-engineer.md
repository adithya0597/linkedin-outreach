# Scoring Engineer Agent

Deterministic validation and hybrid fit scoring.

## Responsibilities
- `CompanyValidator` with 6 checks: employees, funding, AI-native, US HQ, H1B, disqualifiers
- `FitScoringEngine` — hybrid scoring:
  - Deterministic (50pts): H1B (0-15), criteria (0-15), tech overlap (0-10), salary (0-10)
  - Semantic (50pts): profile-JD similarity (0-25), domain-company similarity (0-25)
- `EmbeddingManager` using sentence-transformers/all-MiniLM-L6-v2
- Score breakdown stored per-company in SQLite

## Key Files
- `src/validators/company_validator.py`, `src/validators/scoring_engine.py`, `src/validators/embeddings.py`
