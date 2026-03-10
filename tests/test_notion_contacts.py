"""Tests for Notion contact sync — schema mapping, sync logic, and CRM additions."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM, OutreachORM
from src.integrations.notion_contacts import NotionContactSchemas, NotionContactSync
from src.integrations.notion_sync import NotionCRM

# ---- Fixtures ----


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def sample_contact(db_session):
    """Contact with associated company, flushed to DB."""
    company = CompanyORM(name="TestCorp", tier="Tier 1 - HIGH")
    db_session.add(company)
    db_session.flush()
    contact = ContactORM(
        name="Jane Doe",
        title="CTO",
        company_id=company.id,
        company_name="TestCorp",
        linkedin_url="https://linkedin.com/in/janedoe",
        linkedin_degree=2,
        is_open_profile=True,
        is_recruiter=False,
        contact_score=85.0,
        location="San Francisco, CA",
        recent_posts="Posted about AI agents last week",
    )
    db_session.add(contact)
    db_session.flush()
    return contact


@pytest.fixture
def sync(db_session):
    """NotionContactSync instance with test credentials."""
    return NotionContactSync(
        api_key="test-key",
        contacts_database_id="test-contacts-db",
        session=db_session,
    )


# ---- TestNotionContactSchemas ----


class TestNotionContactSchemas:
    def test_contact_to_notion_valid_properties(self, sample_contact):
        """All ContactORM fields map to correct Notion property types."""
        props = NotionContactSchemas.contact_to_notion(sample_contact)

        assert props["Name"]["title"][0]["text"]["content"] == "Jane Doe"
        assert props["Title"]["rich_text"][0]["text"]["content"] == "CTO"
        assert props["Company"]["rich_text"][0]["text"]["content"] == "TestCorp"
        assert props["LinkedIn URL"]["url"] == "https://linkedin.com/in/janedoe"
        assert props["Degree"]["number"] == 2
        assert props["Contact Score"]["number"] == 85.0
        assert props["Location"]["rich_text"][0]["text"]["content"] == "San Francisco, CA"
        assert props["Notes"]["rich_text"][0]["text"]["content"] == "Posted about AI agents last week"

    def test_checkbox_handling(self, sample_contact):
        """is_open_profile and is_recruiter produce checkbox properties."""
        props = NotionContactSchemas.contact_to_notion(sample_contact)

        assert props["Open Profile"]["checkbox"] is True
        assert props["Is Recruiter"]["checkbox"] is False

    def test_outreach_stage_in_properties(self, sample_contact):
        """Outreach stage is included as a select property."""
        props = NotionContactSchemas.contact_to_notion(
            sample_contact, outreach_stage="Sent"
        )

        assert props["Outreach Stage"]["select"]["name"] == "Sent"

    def test_outreach_stage_default(self, sample_contact):
        """Default outreach stage is 'Not Started'."""
        props = NotionContactSchemas.contact_to_notion(sample_contact)

        assert props["Outreach Stage"]["select"]["name"] == "Not Started"

    def test_notion_to_contact_dict(self):
        """Reverse mapping from Notion page to ORM field dict works correctly."""
        page = {
            "id": "page-abc",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "John Smith"}]},
                "Title": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "VP Engineering"}],
                },
                "Company": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "AcmeAI"}],
                },
                "LinkedIn URL": {
                    "type": "url",
                    "url": "https://linkedin.com/in/johnsmith",
                },
                "Degree": {"type": "number", "number": 1},
                "Open Profile": {"type": "checkbox", "checkbox": True},
                "Is Recruiter": {"type": "checkbox", "checkbox": False},
                "Contact Score": {"type": "number", "number": 90.0},
                "Location": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "NYC"}],
                },
                "Outreach Stage": {
                    "type": "select",
                    "select": {"name": "Connected"},
                },
                "Notes": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Active on LinkedIn"}],
                },
            },
        }

        result = NotionContactSchemas.notion_to_contact_dict(page)

        assert result["name"] == "John Smith"
        assert result["title"] == "VP Engineering"
        assert result["company_name"] == "AcmeAI"
        assert result["linkedin_url"] == "https://linkedin.com/in/johnsmith"
        assert result["linkedin_degree"] == 1
        assert result["is_open_profile"] is True
        assert result["is_recruiter"] is False
        assert result["contact_score"] == 90.0
        assert result["location"] == "NYC"
        assert result["outreach_stage"] == "Connected"
        assert result["recent_posts"] == "Active on LinkedIn"
        assert result["_notion_page_id"] == "page-abc"

    def test_empty_values_skipped(self, db_session):
        """None and empty string values are not included in output."""
        contact = ContactORM(name="Minimal Contact")
        db_session.add(contact)
        db_session.flush()

        props = NotionContactSchemas.contact_to_notion(contact)

        assert "Name" in props
        assert "Outreach Stage" in props  # always present (computed)
        # Empty defaults should be omitted
        assert "Title" not in props
        assert "Company" not in props
        assert "LinkedIn URL" not in props
        assert "Location" not in props
        assert "Notes" not in props


# ---- TestNotionContactSync ----


class TestNotionContactSync:
    @pytest.mark.asyncio
    async def test_dry_run_returns_dict(self, sync, sample_contact):
        """dry_run=True returns properties dict instead of making API calls."""
        result = await sync.sync_contact(sample_contact, dry_run=True)

        assert isinstance(result, dict)
        assert "Name" in result
        assert result["Name"]["title"][0]["text"]["content"] == "Jane Doe"
        assert "Outreach Stage" in result

    @pytest.mark.asyncio
    async def test_push_all_counts(self, sync, sample_contact):
        """push_all_contacts returns correct pushed/skipped/errors counts."""
        with patch.object(sync, "sync_contact", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = "page-id-1"
            results = await sync.push_all_contacts(dry_run=False)

        assert results["pushed"] == 1
        assert results["skipped"] == 0
        assert results["errors"] == []

    @pytest.mark.asyncio
    async def test_push_all_handles_errors(self, sync, sample_contact):
        """push_all_contacts captures errors without crashing."""
        with patch.object(sync, "sync_contact", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = Exception("API down")
            results = await sync.push_all_contacts(dry_run=False)

        assert results["pushed"] == 0
        assert len(results["errors"]) == 1
        assert "Jane Doe" in results["errors"][0]

    def test_outreach_stage_from_orm(self, sync, sample_contact, db_session):
        """_get_outreach_stage queries OutreachORM for most recent stage."""
        outreach = OutreachORM(
            contact_id=sample_contact.id,
            company_name="TestCorp",
            stage="Sent",
            created_at=datetime(2026, 3, 5, 10, 0, 0),
        )
        db_session.add(outreach)
        db_session.flush()

        stage = sync._get_outreach_stage(sample_contact)
        assert stage == "Sent"

    def test_no_outreach_records_returns_not_started(self, sync, sample_contact):
        """Default stage is 'Not Started' when no outreach records exist."""
        stage = sync._get_outreach_stage(sample_contact)
        assert stage == "Not Started"

    def test_last_contact_date(self, sync, sample_contact, db_session):
        """_get_last_contact_date finds most recent sent_at."""
        older = OutreachORM(
            contact_id=sample_contact.id,
            company_name="TestCorp",
            stage="Sent",
            sent_at=datetime(2026, 3, 1, 10, 0, 0),
        )
        newer = OutreachORM(
            contact_id=sample_contact.id,
            company_name="TestCorp",
            stage="Sent",
            sent_at=datetime(2026, 3, 5, 14, 0, 0),
        )
        db_session.add_all([older, newer])
        db_session.flush()

        last_date = sync._get_last_contact_date(sample_contact)
        assert last_date == datetime(2026, 3, 5, 14, 0, 0)

    def test_last_contact_date_none_when_no_sent(self, sync, sample_contact, db_session):
        """Returns None when no outreach has sent_at."""
        outreach = OutreachORM(
            contact_id=sample_contact.id,
            company_name="TestCorp",
            stage="Not Started",
            sent_at=None,
        )
        db_session.add(outreach)
        db_session.flush()

        assert sync._get_last_contact_date(sample_contact) is None


# ---- TestNotionCRMAdditions ----


class TestNotionCRMAdditions:
    @pytest.fixture
    def crm(self):
        return NotionCRM(api_key="test-key", database_id="test-db-id")

    @pytest.mark.asyncio
    async def test_update_company_stage_found(self, crm):
        """update_company_stage updates Stage and returns page_id."""
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {"results": [{"id": "page-xyz"}], "has_more": False},  # find
                {},  # patch
            ]
            result = await crm.update_company_stage("LlamaIndex", "Applied")

        assert result == "page-xyz"
        assert mock_req.call_count == 2
        patch_call = mock_req.call_args_list[1]
        assert patch_call[0][0] == "PATCH"
        payload = patch_call[1]["json"]
        assert payload["properties"]["Stage"]["status"]["name"] == "Applied"

    @pytest.mark.asyncio
    async def test_update_company_stage_not_found(self, crm):
        """update_company_stage returns None when company not found."""
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": [], "has_more": False}
            result = await crm.update_company_stage("NonExistent", "Applied")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_page_ids(self, crm):
        """get_all_page_ids returns name->page_id mapping with pagination."""
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {
                    "results": [
                        {
                            "id": "p1",
                            "properties": {
                                "Company": {
                                    "title": [{"plain_text": "Cursor"}],
                                }
                            },
                        },
                    ],
                    "has_more": True,
                    "next_cursor": "cur-1",
                },
                {
                    "results": [
                        {
                            "id": "p2",
                            "properties": {
                                "Company": {
                                    "title": [{"plain_text": "LlamaIndex"}],
                                }
                            },
                        },
                    ],
                    "has_more": False,
                    "next_cursor": None,
                },
            ]
            mapping = await crm.get_all_page_ids()

        assert mapping == {"Cursor": "p1", "LlamaIndex": "p2"}
        assert mock_req.call_count == 2
        # Second call should include cursor
        second_call = mock_req.call_args_list[1]
        assert second_call[1]["json"]["start_cursor"] == "cur-1"
