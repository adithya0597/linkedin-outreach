"""Tests for Notion CRM sync — schema mapping and property formatting."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.db.orm import CompanyORM
from src.integrations.notion_sync import NotionCRM, NotionSchemas


# ---- Schema Mapping Tests ----


class TestNotionSchemas:
    def test_schema_mapping_full_company(self, sample_valid_company: CompanyORM):
        """CompanyORM with all fields produces correct Notion properties."""
        # Set stage explicitly (Column defaults only apply on DB insert)
        sample_valid_company.stage = "To apply"
        props = NotionSchemas.orm_to_notion(sample_valid_company)

        # Title
        assert props["Company"]["title"][0]["text"]["content"] == "LlamaIndex"

        # Select fields
        assert props["Tier"]["select"]["name"] == "Tier 1 - HIGH"
        assert props["H1B Sponsorship"]["select"]["name"] == "Confirmed"
        assert props["Source Portal"]["select"]["name"] == "Manual"

        # Status
        assert props["Stage"]["status"]["name"] == "To apply"

    def test_schema_mapping_rich_text_fields(self):
        """Rich text fields produce correct Notion format."""
        company = CompanyORM(
            name="TestCo",
            role="AI Engineer",
            hiring_manager="Jane Doe",
            salary_range="$150k-$200k",
            notes="Great culture fit",
        )
        props = NotionSchemas.orm_to_notion(company)

        assert props["Position"]["rich_text"][0]["text"]["content"] == "AI Engineer"
        assert props["Hiring Manager"]["rich_text"][0]["text"]["content"] == "Jane Doe"
        assert props["Salary Range"]["rich_text"][0]["text"]["content"] == "$150k-$200k"
        assert props["Notes"]["rich_text"][0]["text"]["content"] == "Great culture fit"

    def test_schema_mapping_number_field(self):
        """Fit score converts to Notion number."""
        company = CompanyORM(name="TestCo", fit_score=91.5)
        props = NotionSchemas.orm_to_notion(company)

        assert props["Fit Score"]["number"] == 91.5

    def test_schema_mapping_url_field(self):
        """URL field maps correctly."""
        company = CompanyORM(name="TestCo", role_url="https://example.com/jobs/123")
        props = NotionSchemas.orm_to_notion(company)

        assert props["Link"]["url"] == "https://example.com/jobs/123"

    def test_schema_mapping_multi_select_differentiators(self):
        """Comma-separated differentiators become Notion multi_select."""
        company = CompanyORM(
            name="TestCo", differentiators="Graph RAG, Neo4j, Vector DB"
        )
        props = NotionSchemas.orm_to_notion(company)

        ms = props["Differentiators"]["multi_select"]
        assert len(ms) == 3
        assert ms[0]["name"] == "Graph RAG"
        assert ms[1]["name"] == "Neo4j"
        assert ms[2]["name"] == "Vector DB"

    def test_schema_mapping_date_field(self):
        """DateTime fields convert to Notion date format."""
        dt = datetime(2026, 3, 5, 14, 30, 0)
        company = CompanyORM(name="TestCo", created_at=dt)
        props = NotionSchemas.orm_to_notion(company)

        assert props["Applied Date"]["date"]["start"] == "2026-03-05"

    def test_schema_mapping_empty_fields_omitted(self):
        """Empty/None fields are not included in the output."""
        company = CompanyORM(name="TestCo")
        props = NotionSchemas.orm_to_notion(company)

        # Name always present
        assert "Company" in props
        # Empty string defaults should be omitted
        assert "Position" not in props
        assert "Hiring Manager" not in props
        assert "Link" not in props
        assert "Notes" not in props
        # Fit score is None by default
        assert "Fit Score" not in props

    def test_schema_mapping_skeleton_company(self, sample_skeleton_company: CompanyORM):
        """Skeleton entry with minimal data still maps name and tier."""
        props = NotionSchemas.orm_to_notion(sample_skeleton_company)

        assert props["Company"]["title"][0]["text"]["content"] == "10a Labs"
        assert props["Tier"]["select"]["name"] == "Tier 5 - RESCAN"
        assert props["Source Portal"]["select"]["name"] == "Hiring Cafe"


class TestNotionPropertiesFormat:
    """Verify generated properties match exact Notion API format."""

    def test_title_format(self):
        props = NotionSchemas.orm_to_notion(CompanyORM(name="Cursor"))
        title = props["Company"]
        assert "title" in title
        assert isinstance(title["title"], list)
        assert title["title"][0]["text"]["content"] == "Cursor"

    def test_select_format(self):
        props = NotionSchemas.orm_to_notion(
            CompanyORM(name="X", tier="Tier 2 - STRONG")
        )
        sel = props["Tier"]
        assert "select" in sel
        assert "name" in sel["select"]
        assert sel["select"]["name"] == "Tier 2 - STRONG"

    def test_status_format(self):
        props = NotionSchemas.orm_to_notion(CompanyORM(name="X", stage="Applied"))
        st = props["Stage"]
        assert "status" in st
        assert st["status"]["name"] == "Applied"

    def test_rich_text_format(self):
        props = NotionSchemas.orm_to_notion(CompanyORM(name="X", notes="Some note"))
        rt = props["Notes"]
        assert "rich_text" in rt
        assert isinstance(rt["rich_text"], list)
        assert rt["rich_text"][0]["text"]["content"] == "Some note"

    def test_number_format(self):
        props = NotionSchemas.orm_to_notion(CompanyORM(name="X", fit_score=85.0))
        num = props["Fit Score"]
        assert "number" in num
        assert isinstance(num["number"], float)

    def test_url_format(self):
        props = NotionSchemas.orm_to_notion(
            CompanyORM(name="X", role_url="https://x.com/job")
        )
        u = props["Link"]
        assert "url" in u
        assert isinstance(u["url"], str)

    def test_multi_select_format(self):
        props = NotionSchemas.orm_to_notion(
            CompanyORM(name="X", differentiators="A, B")
        )
        ms = props["Differentiators"]
        assert "multi_select" in ms
        assert isinstance(ms["multi_select"], list)
        for item in ms["multi_select"]:
            assert "name" in item

    def test_date_format(self):
        props = NotionSchemas.orm_to_notion(
            CompanyORM(name="X", created_at=datetime(2026, 1, 15))
        )
        d = props["Applied Date"]
        assert "date" in d
        assert "start" in d["date"]
        assert d["date"]["start"] == "2026-01-15"


class TestNotionToDictRoundTrip:
    """Test converting Notion page format back to ORM-compatible dict."""

    def test_notion_to_dict(self):
        """Notion page properties parse to correct ORM field names and values."""
        page = {
            "id": "abc-123",
            "last_edited_time": "2026-03-05T10:00:00.000Z",
            "properties": {
                "Company": {
                    "type": "title",
                    "title": [{"plain_text": "LlamaIndex"}],
                },
                "Tier": {
                    "type": "select",
                    "select": {"name": "Tier 1 - HIGH"},
                },
                "Fit Score": {
                    "type": "number",
                    "number": 91.0,
                },
                "H1B Sponsorship": {
                    "type": "select",
                    "select": {"name": "Confirmed"},
                },
                "Stage": {
                    "type": "status",
                    "status": {"name": "To apply"},
                },
                "Position": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "AI Engineer"}],
                },
                "Link": {
                    "type": "url",
                    "url": "https://jobs.example.com/123",
                },
                "Differentiators": {
                    "type": "multi_select",
                    "multi_select": [
                        {"name": "Graph RAG"},
                        {"name": "Neo4j"},
                    ],
                },
                "Applied Date": {
                    "type": "date",
                    "date": {"start": "2026-03-05"},
                },
            },
        }

        result = NotionSchemas.notion_to_dict(page)

        assert result["name"] == "LlamaIndex"
        assert result["tier"] == "Tier 1 - HIGH"
        assert result["fit_score"] == 91.0
        assert result["h1b_status"] == "Confirmed"
        assert result["stage"] == "To apply"
        assert result["role"] == "AI Engineer"
        assert result["role_url"] == "https://jobs.example.com/123"
        assert result["differentiators"] == "Graph RAG, Neo4j"
        assert result["created_at"] == "2026-03-05"
        assert result["_notion_page_id"] == "abc-123"
        assert result["_notion_updated"] == "2026-03-05T10:00:00.000Z"

    def test_notion_to_dict_empty_fields(self):
        """Empty Notion properties return empty strings / None."""
        page = {
            "id": "xyz-456",
            "last_edited_time": "2026-03-05T10:00:00.000Z",
            "properties": {
                "Company": {"type": "title", "title": []},
                "Tier": {"type": "select", "select": None},
                "Fit Score": {"type": "number", "number": None},
                "Stage": {"type": "status", "status": None},
                "Position": {"type": "rich_text", "rich_text": []},
                "Differentiators": {"type": "multi_select", "multi_select": []},
                "Applied Date": {"type": "date", "date": None},
            },
        }

        result = NotionSchemas.notion_to_dict(page)

        assert result["name"] == ""
        assert result["tier"] == ""
        assert result["fit_score"] is None
        assert result["stage"] == ""
        assert result["role"] == ""
        assert result["differentiators"] == ""
        assert result["created_at"] is None


# ---- NotionCRM Method Tests (mocked HTTP) ----


class TestNotionCRM:
    @pytest.fixture
    def crm(self):
        return NotionCRM(api_key="test-key", database_id="test-db-id")

    @pytest.mark.asyncio
    async def test_find_page_by_name_found(self, crm):
        mock_response = {
            "results": [{"id": "page-123"}],
            "has_more": False,
        }
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            page_id = await crm.find_page_by_name("LlamaIndex")

        assert page_id == "page-123"
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0][0] == "POST"
        payload = call_args[1]["json"]
        assert payload["filter"]["property"] == "Company"
        assert payload["filter"]["title"]["equals"] == "LlamaIndex"

    @pytest.mark.asyncio
    async def test_find_page_by_name_not_found(self, crm):
        mock_response = {"results": [], "has_more": False}
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            page_id = await crm.find_page_by_name("NonExistent")

        assert page_id is None

    @pytest.mark.asyncio
    async def test_sync_company_creates_new(self, crm, sample_valid_company):
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            # find_page_by_name returns no results
            mock_req.side_effect = [
                {"results": [], "has_more": False},  # query for existing
                {"id": "new-page-id"},  # create page
            ]
            page_id = await crm.sync_company(sample_valid_company)

        assert page_id == "new-page-id"
        assert mock_req.call_count == 2
        # Second call should be POST to create
        create_call = mock_req.call_args_list[1]
        assert create_call[0][0] == "POST"
        assert "pages" in create_call[0][1]
        payload = create_call[1]["json"]
        assert payload["parent"]["database_id"] == "test-db-id"
        assert "Company" in payload["properties"]

    @pytest.mark.asyncio
    async def test_sync_company_updates_existing(self, crm, sample_valid_company):
        sample_valid_company.updated_at = datetime(2026, 3, 5, 15, 0, 0)
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {"results": [{"id": "existing-page"}], "has_more": False},
                {"last_edited_time": "2026-03-04T10:00:00.000Z"},  # older
                {},  # patch response
            ]
            page_id = await crm.sync_company(sample_valid_company)

        assert page_id == "existing-page"
        assert mock_req.call_count == 3
        patch_call = mock_req.call_args_list[2]
        assert patch_call[0][0] == "PATCH"

    @pytest.mark.asyncio
    async def test_sync_company_skips_when_notion_newer(
        self, crm, sample_valid_company
    ):
        sample_valid_company.updated_at = datetime(2026, 3, 1, 10, 0, 0)
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {"results": [{"id": "existing-page"}], "has_more": False},
                {"last_edited_time": "2026-03-05T15:00:00.000Z"},  # newer
            ]
            page_id = await crm.sync_company(sample_valid_company)

        assert page_id == "existing-page"
        # Should NOT have made a PATCH call
        assert mock_req.call_count == 2

    @pytest.mark.asyncio
    async def test_pull_all_pagination(self, crm):
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {
                    "results": [
                        {
                            "id": "p1",
                            "last_edited_time": "2026-03-05T10:00:00.000Z",
                            "properties": {
                                "Company": {
                                    "type": "title",
                                    "title": [{"plain_text": "Co1"}],
                                }
                            },
                        }
                    ],
                    "has_more": True,
                    "next_cursor": "cursor-abc",
                },
                {
                    "results": [
                        {
                            "id": "p2",
                            "last_edited_time": "2026-03-05T11:00:00.000Z",
                            "properties": {
                                "Company": {
                                    "type": "title",
                                    "title": [{"plain_text": "Co2"}],
                                }
                            },
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                },
            ]

            results = await crm.pull_all()

        assert len(results) == 2
        assert results[0]["name"] == "Co1"
        assert results[1]["name"] == "Co2"
        # Verify pagination cursor was passed
        second_call = mock_req.call_args_list[1]
        assert second_call[1]["json"]["start_cursor"] == "cursor-abc"

    @pytest.mark.asyncio
    async def test_push_all(self, crm, sample_valid_company, sample_skeleton_company):
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = ["pid-1", "pid-2"]
            ids = await crm.push_all([sample_valid_company, sample_skeleton_company])

        assert ids == ["pid-1", "pid-2"]
        assert mock_sync.call_count == 2

    def test_headers_set_correctly(self, crm):
        assert crm._headers["Authorization"] == "Bearer test-key"
        assert crm._headers["Notion-Version"] == "2022-06-28"
        assert crm._headers["Content-Type"] == "application/json"
