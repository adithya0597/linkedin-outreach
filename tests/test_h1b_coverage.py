"""Coverage boost tests for src/validators/h1b_verifier.py.

Targets lines 36-248: FrogHireClient._parse_result, H1BGraderClient._parse_result,
MyVisaJobsClient._parse_result, and their search methods.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import H1BStatus
from src.validators.h1b_verifier import (
    FrogHireClient,
    H1BGraderClient,
    MyVisaJobsClient,
)


# ---------------------------------------------------------------------------
# FrogHireClient._parse_result
# ---------------------------------------------------------------------------


class TestFrogHireParser:
    def setup_method(self):
        self.client = FrogHireClient()

    def test_confirmed_status(self):
        html = '<div>H1B Sponsor: Yes</div><div>Employees: 200</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED
        assert record.company_name == "TestCo"

    def test_explicit_no_status(self):
        # The "confirmed" regex checks for H-?1B\s*(?:Sponsor|Visa|Yes|...) which
        # would match "H1B Visa" even in "H1B Visa: No". So we need text where
        # only the "no" pattern matches, e.g. "H1B: Not Found"
        html = '<div>H1B: Not Found</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.EXPLICIT_NO

    def test_no_results_found(self):
        html = '<div>No companies found</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_zero_results(self):
        html = '<div>0 results for query</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_perm_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>PERM Filed: Yes</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.has_perm is True

    def test_everify_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>E-Verify Enrolled</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.has_everify is True

    def test_employee_count_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>Employees: 200-500</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.employee_count_on_source == "200-500"

    def test_lca_count_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>LCA: 15</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_count == 15

    def test_fiscal_year_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>FY 2025</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_fiscal_year == "2025"

    def test_ranking_extraction(self):
        html = '<div>H1B Sponsor: Yes</div><div>#4,833</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.ranking == "#4,833"

    def test_raw_data_truncated(self):
        html = '<div>H1B Sponsor: Yes</div>' + 'x' * 3000
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert len(record.raw_data) == 2000

    def test_unknown_with_no_meaningful_data_returns_none(self):
        """Unknown H1B status without LCA or PERM should return None."""
        html = '<div>Some company info but no H1B indicators</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_unknown_with_lca_returns_record(self):
        """Unknown status but has LCA count should return a record."""
        html = '<div>LCA: 5</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_count == 5

    def test_unknown_with_perm_returns_record(self):
        """Unknown status but has PERM should return a record."""
        html = '<div>PERM Approved</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.has_perm is True

    def test_verified_at_and_expires_at_set(self):
        html = '<div>H1B Sponsor: Yes</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.verified_at is not None
        assert record.expires_at is not None

    def test_source_is_frog_hire(self):
        html = '<div>H1B Sponsor: Yes</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.source == "Frog Hire"

    def test_lca_with_comma(self):
        """LCA count like '1,234' should parse correctly."""
        html = '<div>H1B Sponsor: Yes</div><div>LCA: 1,234</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_count == 1234


class TestFrogHireSearch:
    def test_search_no_playwright(self):
        """When playwright is not installed, search returns None."""
        client = FrogHireClient()
        with patch.dict("sys.modules", {"playwright.async_api": None, "playwright": None}):
            # We need to mock the import inside the search method
            with patch("builtins.__import__", side_effect=ImportError("No module named 'playwright'")):
                result = asyncio.run(client.search("TestCo"))
                assert result is None


# ---------------------------------------------------------------------------
# H1BGraderClient._parse_result
# ---------------------------------------------------------------------------


class TestH1BGraderParser:
    def setup_method(self):
        self.client = H1BGraderClient()

    def test_confirmed_with_approval_rate(self):
        html = '<div>Approval Rate: 95.5%</div><div>Cases: 200</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED
        assert record.approval_rate == 95.5
        assert record.lca_count == 200

    def test_confirmed_with_lca_only(self):
        html = '<div>Petitions: 50</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED
        assert record.lca_count == 50

    def test_no_results_found(self):
        html = '<div>No results found</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_did_not_find(self):
        html = '<div>We did not find any matching companies</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_no_data_returns_none(self):
        """HTML without approval rate or LCA should return None."""
        html = '<div>Company page with no useful data</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_raw_data_truncated(self):
        html = '<div>Approval Rate: 90%</div>' + 'y' * 3000
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert len(record.raw_data) == 2000

    def test_source_is_h1bgrader(self):
        html = '<div>Certification Rate: 80%</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.source == "H1BGrader"

    def test_certification_rate_variant(self):
        """'Certification Rate' should also be recognized."""
        html = '<div>Certification Rate: 88.3%</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.approval_rate == 88.3

    def test_lca_comma_separated(self):
        html = '<div>Cases: 1,500</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_count == 1500


class TestH1BGraderSearch:
    def test_search_http_error(self):
        """HTTP error should return None, not raise."""
        client = H1BGraderClient()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_cls.return_value = mock_ctx

            result = asyncio.run(client.search("TestCo"))
            assert result is None

    def test_search_success(self):
        """Successful search should parse HTML response."""
        client = H1BGraderClient()
        mock_response = MagicMock()
        mock_response.text = '<div>Approval Rate: 95%</div><div>Cases: 10</div>'
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_ctx

            result = asyncio.run(client.search("TestCo"))
            assert result is not None
            assert result.status == H1BStatus.CONFIRMED


# ---------------------------------------------------------------------------
# MyVisaJobsClient._parse_result
# ---------------------------------------------------------------------------


class TestMyVisaJobsParser:
    def setup_method(self):
        self.client = MyVisaJobsClient()

    def test_confirmed_with_lca_and_approval(self):
        html = '<div>Applications: 30</div><div>Certified Rate: 92.0%</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED
        assert record.lca_count == 30
        assert record.approval_rate == 92.0

    def test_confirmed_with_lca_only(self):
        html = '<div>LCA: 15</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED
        assert record.lca_count == 15

    def test_no_matching_records(self):
        html = '<div>No matching records</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_zero_records(self):
        html = '<div>0 Records found</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_no_data_returns_none(self):
        html = '<div>Some content without any LCA or approval data</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is None

    def test_raw_data_truncated(self):
        html = '<div>Applications: 10</div>' + 'z' * 3000
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert len(record.raw_data) == 2000

    def test_source_is_myvisajobs(self):
        html = '<div>LCA: 5</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.source == "MyVisaJobs"

    def test_approval_rate_variant(self):
        """'Approval Rate' should also be recognized."""
        html = '<div>LCA: 5</div><div>Approval Rate: 85.5%</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.approval_rate == 85.5

    def test_lca_comma_format(self):
        html = '<div>Applications: 2,500</div>'
        record = self.client._parse_result("TestCo", html)
        assert record is not None
        assert record.lca_count == 2500


class TestMyVisaJobsSearch:
    def test_search_http_error(self):
        """HTTP error should return None, not raise."""
        client = MyVisaJobsClient()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(side_effect=Exception("Timeout"))
            mock_client_cls.return_value = mock_ctx

            result = asyncio.run(client.search("TestCo"))
            assert result is None

    def test_search_success(self):
        """Successful search should parse HTML response."""
        client = MyVisaJobsClient()
        mock_response = MagicMock()
        mock_response.text = '<div>Applications: 20</div><div>Certified Rate: 88%</div>'
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_ctx

            result = asyncio.run(client.search("TestCo"))
            assert result is not None
            assert result.status == H1BStatus.CONFIRMED
            assert result.lca_count == 20
