"""Shared Notion API constants, property converters, and HTTP client base class.

Extracted from notion_sync.py and notion_contacts.py to eliminate duplication.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"


class NotionPropertyConverter:
    """Convert between Python values and Notion API property dicts.

    Supports all Notion property types used across the project:
    title, rich_text, number, select, status, url, multi_select, date, checkbox.
    """

    @staticmethod
    def to_notion(value, notion_type: str) -> dict | None:
        """Convert a Python value to a Notion property dict. Returns None if empty."""
        if value is None or value == "":
            return None

        if notion_type == "title":
            return {"title": [{"text": {"content": str(value)}}]}

        if notion_type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value)}}]}

        if notion_type == "number":
            try:
                return {
                    "number": float(value)
                    if not isinstance(value, (int, float))
                    else value
                }
            except (TypeError, ValueError):
                return None

        if notion_type == "select":
            return {"select": {"name": str(value)}}

        if notion_type == "status":
            return {"status": {"name": str(value)}}

        if notion_type == "url":
            return {"url": str(value)}

        if notion_type == "multi_select":
            # Use pipe delimiter — commas can appear inside tag names
            tags = [t.strip() for t in str(value).split("|") if t.strip()]
            return {"multi_select": [{"name": t} for t in tags]}

        if notion_type == "date":
            if isinstance(value, datetime):
                return {"date": {"start": value.strftime("%Y-%m-%d")}}
            return {"date": {"start": str(value)[:10]}}

        if notion_type == "checkbox":
            return {"checkbox": bool(value)}

        return None

    @staticmethod
    def from_notion(prop: dict, notion_type: str):
        """Convert a Notion property dict back to a Python value."""
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
            return " | ".join(i["name"] for i in items)

        if ptype == "date":
            d = prop.get("date")
            return d["start"] if d else None

        if ptype == "checkbox":
            return prop.get("checkbox", False)

        return None


class NotionAPIClient:
    """Base class for Notion API clients with rate limiting and retry logic."""

    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._min_interval = 1.0 / 3.0  # max 3 req/sec
        self._last_request_time = 0.0

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make a rate-limited HTTP request to Notion API with retry on 429."""
        max_retries = 5
        for attempt in range(max_retries):
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
