"""Bidirectional Notion CRM sync for the LinkedIn outreach project."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx

from src.db.orm import CompanyORM

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"


class NotionSchemas:
    """Maps CompanyORM fields to Notion database properties and back."""

    # Notion property name -> (orm_field, notion_type)
    _FIELD_MAP: dict[str, tuple[str, str]] = {
        "Company": ("name", "title"),
        "Tier": ("tier", "select"),
        "Fit Score": ("fit_score", "number"),
        "H1B Sponsorship": ("h1b_status", "select"),
        "Stage": ("stage", "status"),
        "Position": ("role", "rich_text"),
        "Hiring Manager": ("hiring_manager", "rich_text"),
        "Link": ("role_url", "url"),
        "Salary Range": ("salary_range", "rich_text"),
        "Source Portal": ("source_portal", "select"),
        "Notes": ("notes", "rich_text"),
        "Differentiators": ("differentiators", "multi_select"),
        "Applied Date": ("created_at", "date"),
        "Follow Up": ("updated_at", "date"),
    }

    @classmethod
    def orm_to_notion(cls, company: CompanyORM) -> dict:
        """Convert a CompanyORM instance to Notion page properties dict."""
        props: dict = {}
        for notion_name, (orm_field, notion_type) in cls._FIELD_MAP.items():
            value = getattr(company, orm_field, None)
            prop = cls._to_notion_property(value, notion_type)
            if prop is not None:
                props[notion_name] = prop
        return props

    @classmethod
    def notion_to_dict(cls, page: dict) -> dict:
        """Convert a Notion page object to a flat dict keyed by ORM field names."""
        properties = page.get("properties", {})
        result: dict = {}
        for notion_name, (orm_field, notion_type) in cls._FIELD_MAP.items():
            if notion_name in properties:
                result[orm_field] = cls._from_notion_property(
                    properties[notion_name], notion_type
                )
        result["_notion_page_id"] = page.get("id")
        result["_notion_updated"] = page.get("last_edited_time")
        return result

    # ---- private helpers ----

    @classmethod
    def _to_notion_property(cls, value, notion_type: str) -> dict | None:
        if value is None or value == "":
            return None

        if notion_type == "title":
            return {"title": [{"text": {"content": str(value)}}]}

        if notion_type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value)}}]}

        if notion_type == "number":
            try:
                return {"number": float(value)}
            except (TypeError, ValueError):
                return None

        if notion_type == "select":
            return {"select": {"name": str(value)}}

        if notion_type == "status":
            return {"status": {"name": str(value)}}

        if notion_type == "url":
            return {"url": str(value)}

        if notion_type == "multi_select":
            # Differentiators stored as comma-separated string in ORM
            tags = [t.strip() for t in str(value).split(",") if t.strip()]
            return {"multi_select": [{"name": t} for t in tags]}

        if notion_type == "date":
            if isinstance(value, datetime):
                return {"date": {"start": value.strftime("%Y-%m-%d")}}
            return {"date": {"start": str(value)[:10]}}

        return None

    @classmethod
    def _from_notion_property(cls, prop: dict, notion_type: str):
        ptype = prop.get("type", notion_type)

        if ptype == "title":
            parts = prop.get("title", [])
            return parts[0]["plain_text"] if parts else ""

        if ptype == "rich_text":
            parts = prop.get("rich_text", [])
            return parts[0]["plain_text"] if parts else ""

        if ptype == "number":
            return prop.get("number")

        if ptype == "select":
            sel = prop.get("select")
            return sel["name"] if sel else ""

        if ptype == "status":
            st = prop.get("status")
            return st["name"] if st else ""

        if ptype == "url":
            return prop.get("url", "")

        if ptype == "multi_select":
            items = prop.get("multi_select", [])
            return ", ".join(i["name"] for i in items)

        if ptype == "date":
            d = prop.get("date")
            return d["start"] if d else None

        return None


class NotionCRM:
    """Bidirectional sync between local SQLite and Notion database."""

    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key
        self.database_id = database_id
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._min_interval = 1.0 / 3.0  # max 3 req/sec
        self._last_request_time = 0.0

    # ---- public API ----

    async def find_page_by_name(self, name: str) -> str | None:
        """Search the database for a page with the given Company title. Returns page_id or None."""
        payload = {
            "filter": {
                "property": "Company",
                "title": {"equals": name},
            }
        }
        data = await self._request(
            "POST", f"{NOTION_BASE}/databases/{self.database_id}/query", json=payload
        )
        results = data.get("results", [])
        return results[0]["id"] if results else None

    async def sync_company(self, company: CompanyORM) -> str:
        """Upsert a company to Notion. Returns the page_id."""
        properties = NotionSchemas.orm_to_notion(company)
        page_id = await self.find_page_by_name(company.name)

        if page_id:
            # Check conflict: compare timestamps
            page = await self._request("GET", f"{NOTION_BASE}/pages/{page_id}")
            notion_updated = page.get("last_edited_time", "")
            local_updated = (
                company.updated_at.isoformat() if company.updated_at else ""
            )

            # If Notion was updated more recently, skip the push
            if notion_updated > local_updated:
                return page_id

            await self._request(
                "PATCH",
                f"{NOTION_BASE}/pages/{page_id}",
                json={"properties": properties},
            )
            return page_id
        else:
            data = await self._request(
                "POST",
                f"{NOTION_BASE}/pages",
                json={
                    "parent": {"database_id": self.database_id},
                    "properties": properties,
                },
            )
            return data["id"]

    async def pull_all(self) -> list[dict]:
        """Fetch all pages from the Notion database, handling pagination."""
        all_results: list[dict] = []
        has_more = True
        start_cursor: str | None = None

        while has_more:
            payload: dict = {}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            data = await self._request(
                "POST",
                f"{NOTION_BASE}/databases/{self.database_id}/query",
                json=payload,
            )
            pages = data.get("results", [])
            all_results.extend(NotionSchemas.notion_to_dict(p) for p in pages)
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return all_results

    async def push_all(self, companies: list[CompanyORM]) -> list[str]:
        """Push all companies to Notion via upsert. Returns list of page_ids."""
        page_ids: list[str] = []
        for company in companies:
            pid = await self.sync_company(company)
            page_ids.append(pid)
        return page_ids

    # ---- private helpers ----

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make a rate-limited HTTP request to Notion API with retry on 429."""
        max_retries = 5
        for attempt in range(max_retries):
            # Rate limiting
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

            self._last_request_time = time.monotonic()

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method, url, headers=self._headers, timeout=30.0, **kwargs
                )

            if response.status_code == 429:
                retry_after = float(
                    response.headers.get("Retry-After", 2 ** (attempt + 1))
                )
                await asyncio.sleep(retry_after)
                continue

            response.raise_for_status()
            return response.json()

        raise httpx.HTTPStatusError(
            "Rate limit exceeded after retries",
            request=response.request,
            response=response,
        )
