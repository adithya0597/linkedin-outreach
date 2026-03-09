"""Notion CRM sync for contacts and outreach status."""

from __future__ import annotations

import os
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM, OutreachORM
from src.integrations.notion_base import (
    NOTION_BASE,
    NotionAPIClient,
    NotionPropertyConverter,
)


class NotionContactSchemas:
    """Maps ContactORM fields to Notion database properties."""

    _CONTACT_FIELD_MAP: dict[str, tuple[str, str]] = {
        "Name": ("name", "title"),
        "Title": ("title", "rich_text"),
        "Company": ("company_name", "rich_text"),
        "LinkedIn URL": ("linkedin_url", "url"),
        "Degree": ("linkedin_degree", "number"),
        "Open Profile": ("is_open_profile", "checkbox"),
        "Is Recruiter": ("is_recruiter", "checkbox"),
        "Contact Score": ("contact_score", "number"),
        "Location": ("location", "rich_text"),
        "Outreach Stage": (None, "select"),  # computed from OutreachORM
        "Last Contact": (None, "date"),  # computed from OutreachORM
        "Notes": ("recent_posts", "rich_text"),
    }

    @classmethod
    def contact_to_notion(
        cls, contact: ContactORM, outreach_stage: str = "Not Started"
    ) -> dict:
        """Convert a ContactORM to Notion page properties dict."""
        props: dict = {}
        for notion_name, (orm_field, notion_type) in cls._CONTACT_FIELD_MAP.items():
            if orm_field is None:
                # Computed fields
                if notion_name == "Outreach Stage":
                    props[notion_name] = {"select": {"name": outreach_stage}}
                elif notion_name == "Last Contact":
                    continue  # set separately
                continue

            value = getattr(contact, orm_field, None)
            prop = cls._to_notion_property(value, notion_type)
            if prop is not None:
                props[notion_name] = prop
        return props

    @classmethod
    def notion_to_contact_dict(cls, page: dict) -> dict:
        """Convert a Notion page to a flat dict keyed by ORM field names."""
        properties = page.get("properties", {})
        result: dict = {}
        for notion_name, (orm_field, notion_type) in cls._CONTACT_FIELD_MAP.items():
            if orm_field is None:
                # Handle computed fields
                if notion_name == "Outreach Stage" and notion_name in properties:
                    sel = properties[notion_name].get("select")
                    result["outreach_stage"] = sel["name"] if sel else "Not Started"
                continue
            if notion_name in properties:
                result[orm_field] = cls._from_notion_property(
                    properties[notion_name], notion_type
                )
        result["_notion_page_id"] = page.get("id")
        return result

    # Property converters delegated to shared module
    _to_notion_property = staticmethod(NotionPropertyConverter.to_notion)
    _from_notion_property = staticmethod(NotionPropertyConverter.from_notion)


class NotionContactSync(NotionAPIClient):
    """Sync contacts between local SQLite and Notion database."""

    def __init__(self, api_key: str, contacts_database_id: str, session: Session):
        super().__init__(api_key)
        self.api_key = api_key
        self.contacts_database_id = contacts_database_id
        self.session = session

    def _get_outreach_stage(self, contact: ContactORM) -> str:
        """Get most recent outreach stage for this contact."""
        record = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.contact_id == contact.id)
            .order_by(OutreachORM.created_at.desc())
            .first()
        )
        return record.stage if record else "Not Started"

    def _get_last_contact_date(self, contact: ContactORM) -> datetime | None:
        """Get the most recent sent_at date for this contact."""
        record = (
            self.session.query(OutreachORM)
            .filter(
                OutreachORM.contact_id == contact.id,
                OutreachORM.sent_at.isnot(None),
            )
            .order_by(OutreachORM.sent_at.desc())
            .first()
        )
        return record.sent_at if record else None

    async def _find_contact_page(self, name: str) -> str | None:
        """Search contacts DB for a page with given name."""
        payload = {
            "filter": {
                "property": "Name",
                "title": {"equals": name},
            }
        }
        data = await self._request(
            "POST",
            f"{NOTION_BASE}/databases/{self.contacts_database_id}/query",
            json=payload,
        )
        results = data.get("results", [])
        return results[0]["id"] if results else None

    async def sync_contact(
        self, contact: ContactORM, dry_run: bool = False
    ) -> str | dict:
        """Upsert a single contact to Notion.

        Returns page_id, or properties dict if dry_run.
        """
        outreach_stage = self._get_outreach_stage(contact)
        properties = NotionContactSchemas.contact_to_notion(contact, outreach_stage)

        # Add last contact date if available
        last_contact = self._get_last_contact_date(contact)
        if last_contact:
            properties["Last Contact"] = {
                "date": {"start": last_contact.strftime("%Y-%m-%d")}
            }

        if dry_run:
            return properties

        page_id = await self._find_contact_page(contact.name)
        if page_id:
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
                    "parent": {"database_id": self.contacts_database_id},
                    "properties": properties,
                },
            )
            return data["id"]

    async def push_all_contacts(self, dry_run: bool = False) -> dict:
        """Push all contacts to Notion.

        Returns dict with counts: {pushed, skipped, errors}.
        """
        contacts = self.session.query(ContactORM).all()
        results = {"pushed": 0, "skipped": 0, "errors": []}

        for contact in contacts:
            try:
                result = await self.sync_contact(contact, dry_run=dry_run)
                if result:
                    results["pushed"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                results["errors"].append(f"{contact.name}: {e}")
                logger.error(f"Contact sync failed for {contact.name}: {e}")

        return results

    async def pull_all_contacts(self) -> list[dict]:
        """Fetch all contacts from Notion with pagination."""
        all_results: list[dict] = []
        has_more = True
        start_cursor: str | None = None

        while has_more:
            payload: dict = {}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            data = await self._request(
                "POST",
                f"{NOTION_BASE}/databases/{self.contacts_database_id}/query",
                json=payload,
            )
            pages = data.get("results", [])
            all_results.extend(
                NotionContactSchemas.notion_to_contact_dict(p) for p in pages
            )
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return all_results

    async def sync_outreach_status(self) -> int:
        """Update Notion Applications DB Stage for companies with sent/responded outreach.

        Returns count of companies updated.
        """
        from src.integrations.notion_sync import NotionCRM

        # Find companies with sent or responded outreach
        outreach_records = (
            self.session.query(OutreachORM)
            .filter(OutreachORM.stage.in_(["Sent", "Responded"]))
            .all()
        )

        if not outreach_records:
            return 0

        # Group by company
        company_stages: dict[str, str] = {}
        for record in outreach_records:
            current = company_stages.get(record.company_name, "")
            # Responded > Sent
            if record.stage == "Responded" or current != "Responded":
                company_stages[record.company_name] = record.stage

        # Map outreach stage to Notion Stage
        stage_map = {
            "Sent": "Applied",
            "Responded": "Applied",
        }

        crm = NotionCRM(self.api_key, self._get_applications_db_id())
        updated = 0
        for company_name, outreach_stage in company_stages.items():
            notion_stage = stage_map.get(outreach_stage, "To apply")
            page_id = await crm.find_page_by_name(company_name)
            if page_id:
                await crm._request(
                    "PATCH",
                    f"{NOTION_BASE}/pages/{page_id}",
                    json={
                        "properties": {
                            "Stage": {"status": {"name": notion_stage}},
                        }
                    },
                )
                updated += 1

        return updated

    def _get_applications_db_id(self) -> str:
        """Get applications database ID from config or env."""
        return os.environ.get(
            "NOTION_APPLICATIONS_DB_ID",
            "0c412604-a409-47ab-8c04-29f112c2c683",
        )

    # _request inherited from NotionAPIClient
