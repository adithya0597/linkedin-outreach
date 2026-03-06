"""Extended tests for Notion sync — new fields and dry_run support."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.db.orm import CompanyORM
from src.integrations.notion_sync import NotionCRM, NotionSchemas


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
        """linkedin_url should produce Notion url property format."""
        company = CompanyORM(
            name="TestCo",
            linkedin_url="https://linkedin.com/company/testco",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" in props
        assert props["LinkedIn URL"] == {"url": "https://linkedin.com/company/testco"}

    def test_hm_linkedin_produces_url_format(self):
        """hiring_manager_linkedin should produce Notion url property format."""
        company = CompanyORM(
            name="TestCo",
            hiring_manager_linkedin="https://linkedin.com/in/janedoe",
        )
        props = NotionSchemas.orm_to_notion(company)
        assert "HM LinkedIn" in props
        assert props["HM LinkedIn"] == {"url": "https://linkedin.com/in/janedoe"}

    def test_why_fit_produces_rich_text_format(self):
        """why_fit should produce Notion rich_text property format."""
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
        """best_stats should produce Notion rich_text property format."""
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
        """Empty linkedin_url should not appear in properties."""
        company = CompanyORM(name="TestCo", linkedin_url="")
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" not in props

    def test_none_linkedin_url_excluded(self):
        """None linkedin_url should not appear in properties."""
        company = CompanyORM(name="TestCo")
        # Default is "" which should be excluded
        props = NotionSchemas.orm_to_notion(company)
        assert "LinkedIn URL" not in props

    def test_empty_why_fit_excluded(self):
        """Empty why_fit should not appear in properties."""
        company = CompanyORM(name="TestCo", why_fit="")
        props = NotionSchemas.orm_to_notion(company)
        assert "Why Fit" not in props

    def test_empty_best_stats_excluded(self):
        """Empty best_stats should not appear in properties."""
        company = CompanyORM(name="TestCo", best_stats="")
        props = NotionSchemas.orm_to_notion(company)
        assert "Best Stats" not in props


class TestDryRun:
    def test_dry_run_returns_properties_dict(self):
        """dry_run=True should return properties dict without making API calls."""
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
        """dry_run=True should never call _request."""
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        crm._request = AsyncMock()
        company = CompanyORM(
            name="TestCo",
            tier="Tier 1 - HIGH",
        )
        asyncio.run(crm.sync_company(company, dry_run=True))
        crm._request.assert_not_called()

    def test_dry_run_includes_new_fields(self):
        """dry_run result should include the 4 new fields when populated."""
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
        """Without dry_run, sync_company should call _request (find_page_by_name)."""
        crm = NotionCRM(api_key="fake-key", database_id="fake-db-id")
        # Mock _request to return empty results (no existing page) then a new page
        crm._request = AsyncMock(
            side_effect=[
                {"results": []},  # find_page_by_name returns no match
                {"id": "new-page-id"},  # create page response
            ]
        )
        company = CompanyORM(name="TestCo", tier="Tier 1 - HIGH")
        result = asyncio.run(crm.sync_company(company, dry_run=False))
        assert crm._request.call_count == 2
        assert result == "new-page-id"
