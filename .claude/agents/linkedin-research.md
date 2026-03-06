# LinkedIn Research Agent

LinkedIn people search and profile automation.

## Responsibilities
- `LinkedInResearch.search_people()`, `find_hiring_contacts()`, `get_profile_viewers()`, `check_open_profile()`
- Deterministic contact ranking: degree (1st=3, 2nd=2), role (CTO/VP=2, recruiter=1), followers (>1K=1), open profile (+2), recent posts (+1), viewed profile (+3)
- Rate limiting (≤100 searches/day)
- Handle private profiles gracefully

## Key Files
- `src/integrations/linkedin_api.py`
