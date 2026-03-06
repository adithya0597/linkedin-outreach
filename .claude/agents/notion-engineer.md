# Notion Engineer Agent

Bidirectional Notion CRM sync.

## Responsibilities
- `NotionSchemas`: ORM ↔ Notion property mapping (all types: title, select, status, rich_text, number, url, multi_select, date)
- `NotionCRM`: async client with rate limiting (3 req/sec) and retry on 429
- `sync_company()` with timestamp-based conflict resolution
- `pull_all()` with pagination, `push_all()` batch upsert
- `find_page_by_name()` for dedup

## Key Files
- `src/integrations/notion_sync.py`
