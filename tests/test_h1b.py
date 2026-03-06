"""Tests for H1B verification system — all HTTP calls are mocked."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import H1BStatus, PortalTier
from src.db.orm import CompanyORM, H1BORM
from src.models.h1b import H1BRecord
from src.validators.h1b_verifier import (
    FrogHireClient,
    H1BGraderClient,
    H1BVerifier,
    MyVisaJobsClient,
    _resolve_portal_tier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tier3_company() -> CompanyORM:
    """Tier 3 (YC portal) company — should auto-pass H1B check."""
    return CompanyORM(
        id=1,
        name="Floot",
        source_portal="Work at a Startup (YC)",
        h1b_status="Unknown",
    )


@pytest.fixture
def tier2_company() -> CompanyORM:
    """Tier 2 (general portal) company — needs waterfall verification."""
    return CompanyORM(
        id=2,
        name="LlamaIndex",
        source_portal="Jobright AI",
        h1b_status="Unknown",
    )


@pytest.fixture
def tier1_company() -> CompanyORM:
    """Tier 1 (LinkedIn) company — needs waterfall verification."""
    return CompanyORM(
        id=3,
        name="Cursor",
        source_portal="LinkedIn",
        h1b_status="Unknown",
    )


@pytest.fixture
def mock_froghire() -> FrogHireClient:
    client = FrogHireClient()
    client.search = AsyncMock()
    return client


@pytest.fixture
def mock_h1bgrader() -> H1BGraderClient:
    client = H1BGraderClient()
    client.search = AsyncMock()
    return client


@pytest.fixture
def mock_myvisajobs() -> MyVisaJobsClient:
    client = MyVisaJobsClient()
    client.search = AsyncMock()
    return client


@pytest.fixture
def verifier(mock_froghire, mock_h1bgrader, mock_myvisajobs) -> H1BVerifier:
    return H1BVerifier(
        froghire=mock_froghire,
        h1bgrader=mock_h1bgrader,
        myvisajobs=mock_myvisajobs,
    )


# ---------------------------------------------------------------------------
# test_tier3_auto_pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier3_auto_pass(verifier, tier3_company, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """Tier 3 company returns NOT_APPLICABLE without any HTTP requests."""
    record = await verifier.verify(tier3_company)

    assert record.status == H1BStatus.NOT_APPLICABLE
    assert record.source == "auto_pass"
    assert record.company_name == "Floot"
    assert record.company_id == 1

    # No HTTP clients should have been called
    mock_froghire.search.assert_not_called()
    mock_h1bgrader.search.assert_not_called()
    mock_myvisajobs.search.assert_not_called()


@pytest.mark.asyncio
async def test_tier3_auto_pass_other_portals(verifier, mock_froghire):
    """All Tier 3 portals should auto-pass."""
    tier3_portals = [
        "Wellfound",
        "Work at a Startup (YC)",
        "startup.jobs",
        "Hiring Cafe",
        "Top Startups",
    ]
    for portal in tier3_portals:
        company = CompanyORM(id=10, name="TestCo", source_portal=portal)
        record = await verifier.verify(company)
        assert record.status == H1BStatus.NOT_APPLICABLE, f"Failed for portal {portal}"

    mock_froghire.search.assert_not_called()


# ---------------------------------------------------------------------------
# test_waterfall_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waterfall_froghire_first(verifier, tier2_company, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """FrogHire is tried first; if it returns data, H1BGrader and MyVisaJobs are skipped."""
    froghire_record = H1BRecord(
        company_name="LlamaIndex",
        status=H1BStatus.CONFIRMED,
        source="Frog Hire",
        lca_count=5,
        has_perm=True,
    )
    mock_froghire.search.return_value = froghire_record

    record = await verifier.verify(tier2_company)

    assert record.status == H1BStatus.CONFIRMED
    assert record.source == "Frog Hire"
    assert record.company_id == 2
    mock_froghire.search.assert_called_once_with("LlamaIndex")
    mock_h1bgrader.search.assert_not_called()
    mock_myvisajobs.search.assert_not_called()


@pytest.mark.asyncio
async def test_waterfall_falls_to_h1bgrader(verifier, tier2_company, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """If FrogHire returns None, H1BGrader is tried next."""
    mock_froghire.search.return_value = None
    h1bgrader_record = H1BRecord(
        company_name="LlamaIndex",
        status=H1BStatus.CONFIRMED,
        source="H1BGrader",
        approval_rate=95.0,
    )
    mock_h1bgrader.search.return_value = h1bgrader_record

    record = await verifier.verify(tier2_company)

    assert record.status == H1BStatus.CONFIRMED
    assert record.source == "H1BGrader"
    mock_froghire.search.assert_called_once()
    mock_h1bgrader.search.assert_called_once_with("LlamaIndex")
    mock_myvisajobs.search.assert_not_called()


@pytest.mark.asyncio
async def test_waterfall_falls_to_myvisajobs(verifier, tier2_company, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """If FrogHire and H1BGrader both return None, MyVisaJobs is the last resort."""
    mock_froghire.search.return_value = None
    mock_h1bgrader.search.return_value = None
    mvj_record = H1BRecord(
        company_name="LlamaIndex",
        status=H1BStatus.CONFIRMED,
        source="MyVisaJobs",
        lca_count=12,
    )
    mock_myvisajobs.search.return_value = mvj_record

    record = await verifier.verify(tier2_company)

    assert record.status == H1BStatus.CONFIRMED
    assert record.source == "MyVisaJobs"
    mock_froghire.search.assert_called_once()
    mock_h1bgrader.search.assert_called_once()
    mock_myvisajobs.search.assert_called_once_with("LlamaIndex")


@pytest.mark.asyncio
async def test_waterfall_all_exhausted(verifier, tier2_company, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """If all 3 sources return None, result is UNKNOWN."""
    mock_froghire.search.return_value = None
    mock_h1bgrader.search.return_value = None
    mock_myvisajobs.search.return_value = None

    record = await verifier.verify(tier2_company)

    assert record.status == H1BStatus.UNKNOWN
    assert record.source == "waterfall_exhausted"
    mock_froghire.search.assert_called_once()
    mock_h1bgrader.search.assert_called_once()
    mock_myvisajobs.search.assert_called_once()


# ---------------------------------------------------------------------------
# test_h1b_record_creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h1b_record_fields_populated(verifier, tier2_company, mock_froghire):
    """Verify all H1BRecord fields are correctly populated from source data."""
    froghire_record = H1BRecord(
        company_name="LlamaIndex",
        status=H1BStatus.CONFIRMED,
        source="Frog Hire",
        lca_count=8,
        lca_fiscal_year="2025",
        has_perm=True,
        has_everify=True,
        employee_count_on_source="40-50",
        ranking="#4,833",
        approval_rate=92.5,
        raw_data="<html>truncated</html>",
    )
    mock_froghire.search.return_value = froghire_record

    record = await verifier.verify(tier2_company)

    assert record.company_name == "LlamaIndex"
    assert record.company_id == 2
    assert record.status == H1BStatus.CONFIRMED
    assert record.source == "Frog Hire"
    assert record.lca_count == 8
    assert record.lca_fiscal_year == "2025"
    assert record.has_perm is True
    assert record.has_everify is True
    assert record.employee_count_on_source == "40-50"
    assert record.ranking == "#4,833"
    assert record.approval_rate == 92.5
    assert record.raw_data == "<html>truncated</html>"


def test_tier3_record_has_correct_defaults():
    """Tier 3 auto-pass record has expected default field values."""
    record = H1BRecord(
        company_name="Floot",
        company_id=1,
        status=H1BStatus.NOT_APPLICABLE,
        source="auto_pass",
    )
    assert record.lca_count is None
    assert record.has_perm is False
    assert record.has_everify is False
    assert record.approval_rate is None
    assert record.ranking == ""


# ---------------------------------------------------------------------------
# test_batch_verify_respects_tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_verify_mixed_tiers(verifier, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """Batch with Tier 2 and Tier 3 companies: Tier 3 skips HTTP, Tier 2 uses waterfall."""
    tier3_co = CompanyORM(id=10, name="YCStartup", source_portal="Work at a Startup (YC)")
    tier2_co = CompanyORM(id=20, name="AICompany", source_portal="Jobright AI")

    froghire_record = H1BRecord(
        company_name="AICompany",
        status=H1BStatus.CONFIRMED,
        source="Frog Hire",
        lca_count=15,
    )
    mock_froghire.search.return_value = froghire_record

    results = await verifier.batch_verify([tier3_co, tier2_co])

    assert len(results) == 2

    # Tier 3 company: auto-pass
    assert results[0].status == H1BStatus.NOT_APPLICABLE
    assert results[0].source == "auto_pass"
    assert results[0].company_name == "YCStartup"

    # Tier 2 company: went through waterfall
    assert results[1].status == H1BStatus.CONFIRMED
    assert results[1].source == "Frog Hire"
    assert results[1].company_name == "AICompany"

    # FrogHire was only called once (for the Tier 2 company)
    mock_froghire.search.assert_called_once_with("AICompany")


@pytest.mark.asyncio
async def test_batch_verify_all_tier3(verifier, mock_froghire, mock_h1bgrader, mock_myvisajobs):
    """Batch of only Tier 3 companies makes zero HTTP requests."""
    companies = [
        CompanyORM(id=i, name=f"Startup{i}", source_portal="Wellfound")
        for i in range(5)
    ]

    results = await verifier.batch_verify(companies)

    assert len(results) == 5
    assert all(r.status == H1BStatus.NOT_APPLICABLE for r in results)
    mock_froghire.search.assert_not_called()
    mock_h1bgrader.search.assert_not_called()
    mock_myvisajobs.search.assert_not_called()


@pytest.mark.asyncio
async def test_batch_verify_persists_to_db(verifier, tier2_company, mock_froghire, session):
    """When session is provided, batch_verify saves H1BORM and updates CompanyORM."""
    # Add company to DB first
    session.add(tier2_company)
    session.commit()

    froghire_record = H1BRecord(
        company_name="LlamaIndex",
        status=H1BStatus.CONFIRMED,
        source="Frog Hire",
        lca_count=5,
        has_perm=True,
        has_everify=True,
        approval_rate=90.0,
    )
    mock_froghire.search.return_value = froghire_record

    results = await verifier.batch_verify([tier2_company], session=session)

    assert len(results) == 1

    # Check H1BORM was created
    h1b_rows = session.query(H1BORM).all()
    assert len(h1b_rows) == 1
    assert h1b_rows[0].status == "Confirmed"
    assert h1b_rows[0].source == "Frog Hire"
    assert h1b_rows[0].lca_count == 5

    # Check CompanyORM was updated
    company = session.query(CompanyORM).filter_by(name="LlamaIndex").first()
    assert company.h1b_status == "Confirmed"
    assert company.h1b_source == "Frog Hire"
    assert "LCA: 5" in company.h1b_details
    assert "PERM: Yes" in company.h1b_details
    assert "E-Verify: Yes" in company.h1b_details
    assert "Approval: 90.0%" in company.h1b_details


# ---------------------------------------------------------------------------
# test_resolve_portal_tier (unit helper)
# ---------------------------------------------------------------------------


def test_resolve_portal_tier_tier3():
    co = CompanyORM(source_portal="Work at a Startup (YC)")
    assert _resolve_portal_tier(co) == PortalTier.TIER_3


def test_resolve_portal_tier_tier1():
    co = CompanyORM(source_portal="LinkedIn")
    assert _resolve_portal_tier(co) == PortalTier.TIER_1


def test_resolve_portal_tier_tier2():
    co = CompanyORM(source_portal="Jobright AI")
    assert _resolve_portal_tier(co) == PortalTier.TIER_2


def test_resolve_portal_tier_unknown_defaults_tier2():
    co = CompanyORM(source_portal="SomeRandomPortal")
    assert _resolve_portal_tier(co) == PortalTier.TIER_2


# ---------------------------------------------------------------------------
# test_linkedin_tier1_uses_waterfall
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier1_linkedin_uses_waterfall(verifier, tier1_company, mock_froghire):
    """Tier 1 (LinkedIn) company goes through waterfall, not auto-pass."""
    froghire_record = H1BRecord(
        company_name="Cursor",
        status=H1BStatus.CONFIRMED,
        source="Frog Hire",
    )
    mock_froghire.search.return_value = froghire_record

    record = await verifier.verify(tier1_company)

    assert record.status == H1BStatus.CONFIRMED
    mock_froghire.search.assert_called_once_with("Cursor")
