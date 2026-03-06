# Outreach Builder Agent

Jinja2 templates, char validation, and sequence builder.

## Responsibilities
- 8 Jinja2 templates: connection_request (a/b/c), follow_up (a/b), inmail, pre_engagement, profile_viewer
- `OutreachTemplateEngine` with `render()` and char limit enforcement
- `CharCounter`: connection request ≤300, InMail ≤400, comment ≤280
- `SequenceBuilder`: 14-day multi-touch calendar with Tue/Thu scheduling
- `OutreachPersonalizer`: thin LLM layer for 1-2 sentence hooks only

## Key Files
- `src/outreach/template_engine.py`, `src/outreach/templates/*.j2`
