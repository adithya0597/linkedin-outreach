"""Tests for Notion CRM sync -- schema mapping, property formatting, new fields,
dry_run support, batch sync (parallel push + incremental pull).

Consolidated from: test_notion.py, test_notion_push.py,
test_notion_sync_extended.py, test_notion_batch_sync.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM
from src.integrations.notion_sync import NotionCRM, NotionSchemas


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def crm():
    return NotionCRM(api_key="test-key", database_id="test-db-id")


@pytest.fixture()
def companies():
    return [
        CompanyORM(name="Company A"),
        CompanyORM(name="Company B"),
        CompanyORM(name="Company C"),
    ]


# ===========================================================================
# Schema mapping tests (from test_notion.py)
# ===========================================================================


class TestNotionSchemas:
    def test_schema_mapping_full_company(self, sample_valid_company: CompanyORM):
        """CompanyORM with all fields produces correct Notion properties."""
        sample_valid_company.stage = "To apply"
        props = NotionSchemas.orm_to_notion(sample_valid_company)

        assert props["Company"]["title"][0]["text"]["content"] == "LlamaIndex"
        assert props["Tier"]["select"]["name"] == "Tier 1 - HIGH"
        assert props["H1B Sponsorship"]["select"]["name"] == "Confirmed"
        assert props["Source Portal"]["select"]["name"] == "Manual"
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

        assert "Company" in props
        assert "Position" not in props
        assert "Hiring Manager" not in props
        assert "Link" not in props
        assert "Notes" not in props
        assert "Fit Score" not in props

    def test_schema_mapping_skeleton_company(self, sample_skeleton_company: CompanyORM):
        """Skeleton entry with minimal data still maps name and tier."""
        props = NotionSchemas.orm_to_notion(sample_skeleton_company)

        assert props["Company"]["title"][0]["text"]["content"] == "10a Labs"
        assert props["Tier"]["select"]["name"] == "Tier 5 - RESCAN"
        assert props["Source Portal"]["select"]["name"] == "Hiring Cafe"


# ===========================================================================
# Notion API property format tests (from test_notion.py)
# ===========================================================================


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


# ===========================================================================
# Notion -> dict round-trip tests (from test_notion.py)
# ===========================================================================


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


# ===========================================================================
# NotionCRM method tests -- mocked HTTP (from test_notion.py)
# ===========================================================================


class TestNotionCRM:
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
            mock_req.side_effect = [
                {"results": [], "has_more": False},
                {"id": "new-page-id"},
            ]
            page_id = await crm.sync_company(sample_valid_company)

        assert page_id == "new-page-id"
        assert mock_req.call_count == 2
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
                {"last_edited_time": "2026-03-04T10:00:00.000Z"},
                {},
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
                {"last_edited_time": "2026-03-05T15:00:00.000Z"},
            ]
            page_id = await crm.sync_company(sample_valid_company)

        assert page_id == "existing-page"
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


# ===========================================================================
# New fields in field map (from test_notion_sync_extended.py)
# ===========================================================================


class TestNewFieldsInFieldMap:
    def test_linkedin_url_in_field_map(self):
        """LinkedIn URL field must exist in _FIELD_MAP with url type."""
        assert "LinkedIn URL" in NotionSchemas._FIELD_MAP
        orm_field, notion_type = NotionSchemas._FIELD_MAP["LinkedIn URL"]
        assert orm_field == "linkedin_url"
        assert notion_type == "url"

    def test_hm_linkedin_in_field_map(self):
        """HM LinkedIn field must exist in _FIELD_MAP with url type."""
        assert "HM LinkedIn" in NotionSchemas._FIELD_MAP
        orm_field, notion_type = NotionSchemas._FIELD_MAP["HM LinkedIn"]
        assert orm_field == "hiring_manager_linkedin"
        assert notion_type == "url"

    def test_why_fit_in_field_map(self):
        """Why Fit field must exist in _FIELD_MAP with rich_text type."""
        assert "Why Fit" in NotionSchemas._FIELD_MAP
        orm_field, notion_type = NotionSchemas._FIELD_MAP["Why Fit"]
        assert orm_field == "why_fit"
        assert notion_type == "rich_text"

    def test_best_stats_in_field_map(self):
        """Best Stats field must exist in _FIELD_MAP with rich_text type."""
        assert "Best Stats" in NotionSchemas._FIELD_MAP
        orm_field, notion_type = NotionSchemas._FIELD_MAP["Best Stats"]
        assert orm_field == "best_stats"
        assert notion_type == "rich_text"


class TestNewFieldPropertyFormats:
    def test_linkedin_url_produces_url_format(self):
        company = CompanyORM(
            name="TestCo",
            linkedin_url="https://linkedin.com/company/testco",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" in props
        assert props["LinkedIn URL"] == {"url": "https://linkedin.com/company/testco"}

    def test_hm_linkedin_produces_url_format(self):
        company = CompanyORM(
            name="TestCo",
            hiring_manager_linkedin="https://linkedin.com/in/janedoe",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "HM LinkedIn" in props
        assert props["HM LinkedIn"] == {"url": "https://linkedin.com/in/janedoe"}

    def test_why_fit_produces_rich_text_format(self):
        company = CompanyORM(
            name="TestCo",
            why_fit="Graph RAG expertise matches their core product",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "Why Fit" in props
        assert props["Why Fit"] == {
            "rich_text": [{"text": {"content": "Graph RAG expertise matches their core product"}}]
        }

    def test_best_stats_produces_rich_text_format(self):
        company = CompanyORM(
            name="TestCo",
            best_stats="138-node semantic graph, 90% automation",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "Best Stats" in props
        assert props["Best Stats"] == {
            "rich_text": [{"text": {"content": "138-node semantic graph, 90% automation"}}]
        }


class TestEmptyFieldsExcluded:
    def test_empty_linkedin_url_excluded(self):
        company = CompanyORM(name="TestCo", linkedin_url="")
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" not in props

    def test_none_linkedin_url_excluded(self):
        company = CompanyORM(name="TestCo")
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" not in props

    def test_empty_why_fit_excluded(self):
        company = CompanyORM(name="TestCo", why_fit="")
        props = NotionSchemas.orm_to_notion(company)
        assert "Why Fit" not in props

    def test_empty_best_stats_excluded(self):
        company = CompanyORM(name="TestCo", best_stats="")
        props = NotionSchemas.orm_to_notion(company)
        assert "Best Stats" not in props


# ===========================================================================
# Dry-run tests (from test_notion_sync_extended.py)
# ===========================================================================


class TestDryRun:
    def test_dry_run_returns_properties_dict(self):
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        company = CompanyORM(
            name="TestCo",
            tier="Tier 1 - HIGH",
            linkedin_url="https://linkedin.com/company/testco",
            why_fit="Strong graph RAG match",
        )
        result = asyncio.run(crm.sync_company(company, dry_run=True))
        assert isinstance(result, dict)
        assert "Company" in result
        assert result["Company"] == {"title": [{"text": {"content": "TestCo"}}]}

    def test_dry_run_does_not_call_request(self):
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        crm._request = AsyncMock()
        company = CompanyORM(
            name="TestCo",
            tier="Tier 1 - HIGH",
        )
        asyncio.run(crm.sync_company(company, dry_run=True))
        crm._request.assert_not_called()

    def test_dry_run_includes_new_fields(self):
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        company = CompanyORM(
            name="TestCo",
            linkedin_url="https://linkedin.com/company/testco",
            hiring_manager_linkedin="https://linkedin.com/in/janedoe",
            why_fit="Perfect graph match",
            best_stats="138-node graph, 90% automation",
        )
        result = asyncio.run(crm.sync_company(company, dry_run=True))
        assert "LinkedIn URL" in result
        assert "HM LinkedIn" in result
        assert "Why Fit" in result
        assert "Best Stats" in result

    def test_non_dry_run_calls_request(self):
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        crm._request = AsyncMock(
            side_effect=[
                {"results": []},
                {"id": "new-page-id"},
            ]
        )
        company = CompanyORM(name="TestCo", tier="Tier 1 - HIGH")
        result = asyncio.run(crm.sync_company(company, dry_run=False))
        assert crm._request.call_count == 2
        assert result == "new-page-id"


# ===========================================================================
# Parallel push tests (from test_notion_batch_sync.py)
# ===========================================================================


class TestPushAllParallel:
    """Verify semaphore-limited parallel push behaviour."""

    @pytest.mark.asyncio
    async def test_push_all_parallel_calls_push_for_each(self, crm, companies):
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = ["page-a", "page-b", "page-c"]
            results = await crm.push_all_parallel(companies, max_concurrent=3)

        assert mock_sync.call_count == 3
        assert results == ["page-a", "page-b", "page-c"]

    @pytest.mark.asyncio
    async def test_push_all_parallel_respects_max_concurrent(self, crm, companies):
        max_concurrent = 2
        active_count = 0
        max_observed = 0

        original_sync = AsyncMock(side_effect=["p1", "p2", "p3"])

        async def tracking_sync(company):
            nonlocal active_count, max_observed
            active_count += 1
            max_observed = max(max_observed, active_count)
            result = await original_sync(company)
            await asyncio.sleep(0.01)
            active_count -= 1
            return result

        with patch.object(crm, "sync_company", side_effect=tracking_sync):
            results = await crm.push_all_parallel(
                companies, max_concurrent=max_concurrent
            )

        assert max_observed <= max_concurrent
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_push_all_parallel_handles_errors_gracefully(self, crm, companies):
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = [
                "page-a",
                Exception("API error"),
                "page-c",
            ]
            results = await crm.push_all_parallel(companies, max_concurrent=3)

        assert "page-a" in results
        assert "page-c" in results
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_push_all_parallel_returns_page_ids(self, crm, companies):
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = ["id-1", "id-2", "id-3"]
            results = await crm.push_all_parallel(companies)

        assert results == ["id-1", "id-2", "id-3"]
        for r in results:
            assert isinstance(r, str)

    @pytest.mark.asyncio
    async def test_push_all_parallel_empty_list(self, crm):
        results = await crm.push_all_parallel([], max_concurrent=3)
        assert results == []


# ===========================================================================
# Incremental pull tests (from test_notion_batch_sync.py)
# ===========================================================================


class TestPullSince:
    """Verify incremental pull with last_edited_time filter."""

    @pytest.mark.asyncio
    async def test_pull_since_builds_correct_filter(self, crm):
        timestamp = "2026-03-05T12:00:00"
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": []}
            await crm.pull_since(timestamp)

        mock_req.assert_called_once()
        call_args = mock_req.call_args
        payload = call_args[1]["json"]
        assert payload["filter"]["timestamp"] == "last_edited_time"
        assert payload["filter"]["last_edited_time"]["after"] == timestamp

    @pytest.mark.asyncio
    async def test_pull_since_returns_pages(self, crm):
        pages = [
            {"id": "page-1", "properties": {}},
            {"id": "page-2", "properties": {}},
        ]
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": pages}
            result = await crm.pull_since("2026-03-05T12:00:00")

        assert len(result) == 2
        assert result[0]["id"] == "page-1"
        assert result[1]["id"] == "page-2"

    @pytest.mark.asyncio
    async def test_pull_since_no_results_returns_empty(self, crm):
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": []}
            result = await crm.pull_since("2026-03-06T00:00:00")

        assert result == []

    @pytest.mark.asyncio
    async def test_pull_since_handles_api_error(self, crm):
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("Network error")
            result = await crm.pull_since("2026-03-05T12:00:00")

        assert result == []


class TestIncrementalPullIntegration:
    """Integration-style test: incremental pull uses sync state timestamp."""

    @pytest.mark.asyncio
    async def test_incremental_pull_uses_sync_state(self, tmp_path):
        from src.integrations.notion_incremental import NotionSyncState

        state_path = str(tmp_path / "sync_state.json")
        state = NotionSyncState(state_path=state_path)
        state.update_last_sync("2026-03-05T10:00:00")

        crm = NotionCRM(api_key="test-key", database_id="test-db-id")

        with patch.object(crm, "pull_since", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = [{"id": "page-1"}]

            last_sync = state.get_last_sync()
            assert last_sync is not None
            result = await crm.pull_since(last_sync)

        mock_pull.assert_called_once_with("2026-03-05T10:00:00")
        assert len(result) == 1


# ===========================================================================
# Push updates tests (from test_notion_push.py)
# ===========================================================================


# These tests use NotionBidirectionalSync which requires its own DB session
# and separate fixtures to avoid conflicts with the crm fixture above.

from src.integrations.notion_bidirectional import NotionBidirectionalSync


@pytest.fixture()
def push_db_session():
    """Create an in-memory SQLite session with the schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def sync(push_db_session, tmp_path):
    """Return a NotionBidirectionalSync wired to the test session."""
    return NotionBidirectionalSync(
        api_key="test-key",
        database_id="test-db-id",
        session=push_db_session,
        sync_state_path=str(tmp_path / "test_sync_state.json"),
    )


def _add_company(
    session,
    name: str,
    updated_at: datetime | None = None,
    last_synced_at: datetime | None = None,
    **fields,
) -> CompanyORM:
    """Insert a CompanyORM row into the test DB."""
    company = CompanyORM(
        name=name,
        updated_at=updated_at or datetime(2026, 3, 5, 10, 0, 0),
        last_synced_at=last_synced_at,
        **fields,
    )
    session.add(company)
    session.commit()
    return company


class TestPushUpdatesUnsyncedRecords:
    """Unsynced records (last_synced_at is None) are found by push_updates."""

    @pytest.mark.asyncio
    async def test_unsynced_records_are_pushed(self, sync, push_db_session):
        _add_company(
            push_db_session,
            "Acme AI",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
            tier="Tier 1",
        )
        _add_company(
            push_db_session,
            "Beta Corp",
            updated_at=datetime(2026, 3, 5, 14, 0, 0),
            last_synced_at=None,
            tier="Tier 2",
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.push_updates(dry_run=False)

        assert result["pushed"] == 2
        assert result["push_errors"] == []
        assert result["skipped"] == 0


class TestSyncedRecordsSkipped:
    """Synced records (last_synced_at > updated_at) are skipped by push_updates."""

    @pytest.mark.asyncio
    async def test_already_synced_records_are_skipped(self, sync, push_db_session):
        _add_company(
            push_db_session,
            "Already Synced Corp",
            updated_at=datetime(2026, 3, 5, 10, 0, 0),
            last_synced_at=datetime(2026, 3, 5, 12, 0, 0),
            tier="Tier 1",
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ) as mock_sync:
            result = await sync.push_updates(dry_run=False)

        assert result["pushed"] == 0
        mock_sync.assert_not_called()


class TestDryRunCountsOnly:
    """Dry run counts records but doesn't push to Notion."""

    @pytest.mark.asyncio
    async def test_dry_run_counts_without_pushing(self, sync, push_db_session):
        _add_company(
            push_db_session,
            "DryRun Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
        )
        _add_company(
            push_db_session,
            "DryRun Corp 2",
            updated_at=datetime(2026, 3, 5, 14, 0, 0),
            last_synced_at=datetime(2026, 3, 5, 10, 0, 0),
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock
        ) as mock_sync:
            result = await sync.push_updates(dry_run=True)

        assert result["pushed"] == 2
        assert result["push_errors"] == []
        mock_sync.assert_not_called()

        for company in push_db_session.query(CompanyORM).all():
            if company.name == "DryRun Corp":
                assert company.last_synced_at is None
            elif company.name == "DryRun Corp 2":
                assert company.last_synced_at == datetime(2026, 3, 5, 10, 0, 0)


class TestFullSyncIncludesPushStats:
    """full_sync includes push stats (pushed, push_errors) in its result dict."""

    @pytest.mark.asyncio
    async def test_full_sync_returns_push_stats(self, sync, push_db_session):
        _add_company(
            push_db_session,
            "PushMe Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
            tier="Tier 2",
        )

        fake_records = [
            {
                "name": "PushMe Corp",
                "_notion_page_id": "page-pushme",
                "_notion_updated": "2026-03-05T10:00:00.000Z",
                "tier": "Tier 2",
            },
        ]

        with patch.object(
            sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records
        ), patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.full_sync(dry_run=False)

        assert "pushed" in result
        assert "push_errors" in result
        assert isinstance(result["pushed"], int)
        assert isinstance(result["push_errors"], list)
        assert result["pushed"] >= 1


class TestLastSyncedAtUpdatedAfterPush:
    """last_synced_at is updated after a successful push."""

    @pytest.mark.asyncio
    async def test_last_synced_at_stamped_on_success(self, sync, push_db_session):
        company = _add_company(
            push_db_session,
            "Stamp Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
        )

        before_push = datetime.now()

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.push_updates(dry_run=False)

        after_push = datetime.now()

        assert result["pushed"] == 1

        push_db_session.refresh(company)
        assert company.last_synced_at is not None
        assert before_push <= company.last_synced_at <= after_push


class TestCompanyORMHasLastSyncedAt:
    """CompanyORM has the last_synced_at column."""

    def test_last_synced_at_column_exists(self, push_db_session):
        company = CompanyORM(name="Schema Test Corp")
        push_db_session.add(company)
        push_db_session.commit()

        fetched = push_db_session.query(CompanyORM).filter_by(name="Schema Test Corp").first()
        assert fetched is not None
        assert hasattr(fetched, "last_synced_at")
        assert fetched.last_synced_at is None

    def test_last_synced_at_can_be_set(self, push_db_session):
        now = datetime(2026, 3, 6, 10, 0, 0)
        company = CompanyORM(name="Timestamp Corp", last_synced_at=now)
        push_db_session.add(company)
        push_db_session.commit()

        fetched = push_db_session.query(CompanyORM).filter_by(name="Timestamp Corp").first()
        assert fetched.last_synced_at == now
