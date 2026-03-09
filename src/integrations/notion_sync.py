"""Bidirectional Notion CRM sync for the LinkedIn outreach project."""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from src.db.orm import CompanyORM
from src.integrations.notion_base import (
    NOTION_BASE,
    NotionAPIClient,
    NotionPropertyConverter,
)


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
        "LinkedIn URL": ("linkedin_url", "url"),
        "HM LinkedIn": ("hiring_manager_linkedin", "url"),
        "Why Fit": ("why_fit", "rich_text"),
        "Best Stats": ("best_stats", "rich_text"),
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

    # ---- private helpers (delegated to shared converter) ----

    _to_notion_property = staticmethod(NotionPropertyConverter.to_notion)
    _from_notion_property = staticmethod(NotionPropertyConverter.from_notion)


class NotionCRM(NotionAPIClient):
    """Bidirectional sync between local SQLite and Notion database."""

    def __init__(self, api_key: str, database_id: str):
        super().__init__(api_key)
        self.api_key = api_key
        self.database_id = database_id

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

    async def sync_company(self, company: CompanyORM, dry_run: bool = False) -> str | dict:
        """Upsert a company to Notion. Returns the page_id (or properties dict if dry_run)."""
        properties = NotionSchemas.orm_to_notion(company)

        if dry_run:
            return properties

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

    async def update_company_stage(self, company_name: str, new_stage: str) -> str | None:
        """Update the Stage status field for a company. Returns page_id or None."""
        page_id = await self.find_page_by_name(company_name)
        if not page_id:
            return None
        await self._request(
            "PATCH",
            f"{NOTION_BASE}/pages/{page_id}",
            json={"properties": {"Stage": {"status": {"name": new_stage}}}},
        )
        return page_id

    async def get_all_page_ids(self) -> dict[str, str]:
        """Get all company name -> page_id mappings, handling pagination."""
        mapping: dict[str, str] = {}
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
            for page in data.get("results", []):
                title_prop = page.get("properties", {}).get("Company", {}).get("title", [])
                if title_prop:
                    name = title_prop[0].get("plain_text", "")
                    if name:
                        mapping[name] = page["id"]
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return mapping

    async def push_all_parallel(
        self, companies: list, max_concurrent: int = 3
    ) -> list[str]:
        """Push with semaphore-limited concurrency.

        Each company is pushed via sync_company in parallel, with at most
        *max_concurrent* in-flight requests.  Failures are logged and skipped;
        one failure does not stop the rest.
        """
        sem = asyncio.Semaphore(max_concurrent)
        results: list[str] = []

        async def _push_one(company):
            async with sem:
                try:
                    page_id = await self.sync_company(company)
                    return page_id
                except Exception as e:
                    logger.warning(f"Failed to push {company.name}: {e}")
                    return None

        tasks = [_push_one(c) for c in companies]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in raw_results:
            if isinstance(r, str):
                results.append(r)
            elif isinstance(r, dict) and not isinstance(r, Exception):
                results.append(str(r))

        return results

    async def pull_since(self, last_edited_after: str) -> list[dict]:
        """Pull pages edited after ISO timestamp using Notion filter."""
        try:
            filter_payload = {
                "filter": {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {
                        "after": last_edited_after,
                    },
                }
            }

            resp = await self._request(
                "POST",
                f"{NOTION_BASE}/databases/{self.database_id}/query",
                json=filter_payload,
            )
            return resp.get("results", [])
        except Exception as e:
            logger.warning(f"Pull since {last_edited_after} failed: {e}")
            return []
