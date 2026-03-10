"""Tests for H1B verifier — regex hardening, parallel consensus, and tier handling."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.enums import H1BStatus, PortalTier
from src.db.orm import CompanyORM
from src.models.h1b import H1BRecord
from src.validators.h1b_verifier import (
    H1BVerifier,
    FrogHireClient,
    H1BGraderClient,
    MyVisaJobsClient,
    _build_consensus,
    _resolve_portal_tier,
    classify_h1b_text,
)


# ---------------------------------------------------------------------------
# classify_h1b_text — regex hardening
# ---------------------------------------------------------------------------


class TestClassifyH1BText:
    """Tests for the shared H1B text classifier with negative lookahead."""

    # --- Should be CONFIRMED ---

    def test_h1b_sponsor_yes(self):
        assert classify_h1b_text("H1B Sponsor: Yes") == H1BStatus.CONFIRMED

    def test_h1b_visa_sponsorship_available(self):
        assert classify_h1b_text("H1B Visa Sponsorship Available") == H1BStatus.CONFIRMED

    def test_sponsors_h1b(self):
        assert classify_h1b_text("Company Sponsors H1B visas") == H1BStatus.CONFIRMED

    def test_h1b_checkmark(self):
        assert classify_h1b_text("H-1B ✓") == H1BStatus.CONFIRMED

    def test_h1b_green_check(self):
        assert classify_h1b_text("H1B ✅") == H1BStatus.CONFIRMED

    def test_h1b_visa_yes(self):
        assert classify_h1b_text("H1B Visa: Yes") == H1BStatus.CONFIRMED

    def test_h1b_sponsor_no_dash(self):
        assert classify_h1b_text("H1B Sponsor") == H1BStatus.CONFIRMED

    def test_h1b_with_dash(self):
        assert classify_h1b_text("H-1B Sponsor: Yes, actively sponsoring") == H1BStatus.CONFIRMED

    # --- Should be EXPLICIT_NO (false positive prevention) ---

    def test_h1b_visa_denied(self):
        """The original bug: 'H1B Visa Denied' was matching as CONFIRMED."""
        assert classify_h1b_text("H1B Visa Denied") == H1BStatus.EXPLICIT_NO

    def test_does_not_sponsor_h1b(self):
        assert classify_h1b_text("Does not sponsor H1B visas") == H1BStatus.EXPLICIT_NO

    def test_doesnt_sponsor_h1b(self):
        assert classify_h1b_text("Doesn't sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_not_sponsor_h1b(self):
        assert classify_h1b_text("Not sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_no_sponsor_h1b(self):
        assert classify_h1b_text("No sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_unable_to_sponsor_h1b(self):
        assert classify_h1b_text("Unable to sponsor H1B visas at this time") == H1BStatus.EXPLICIT_NO

    def test_cannot_sponsor_h1b(self):
        assert classify_h1b_text("Cannot sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_will_not_sponsor(self):
        assert classify_h1b_text("Will not sponsor H1B visas") == H1BStatus.EXPLICIT_NO

    def test_h1b_no_cross(self):
        assert classify_h1b_text("H1B ✗") == H1BStatus.EXPLICIT_NO

    def test_h1b_red_x(self):
        assert classify_h1b_text("H1B ❌") == H1BStatus.EXPLICIT_NO

    def test_h1b_not_found(self):
        assert classify_h1b_text("H1B Not Found in records") == H1BStatus.EXPLICIT_NO

    def test_no_longer_sponsor_h1b(self):
        assert classify_h1b_text("No longer sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_cant_sponsor_h1b(self):
        assert classify_h1b_text("Can't sponsor H1B visas") == H1BStatus.EXPLICIT_NO

    # --- Should be UNKNOWN ---

    def test_no_h1b_mention(self):
        assert classify_h1b_text("We are hiring engineers for our team") == H1BStatus.UNKNOWN

    def test_empty_string(self):
        assert classify_h1b_text("") == H1BStatus.UNKNOWN

    def test_unrelated_content(self):
        assert classify_h1b_text("<html><body>Company profile page</body></html>") == H1BStatus.UNKNOWN

    # --- Edge cases ---

    def test_mixed_signals_denial_wins(self):
        """When denial and confirmation are both present, denial wins (checked first)."""
        html = "H1B Sponsor: Yes... Update: Company does not sponsor H1B anymore"
        assert classify_h1b_text(html) == H1BStatus.EXPLICIT_NO

    def test_case_insensitive(self):
        assert classify_h1b_text("h1b sponsor: yes") == H1BStatus.CONFIRMED

    def test_h1b_denied_in_longer_text(self):
        html = """
        <div class="company-info">
            <h2>Visa Sponsorship</h2>
            <p>H1B Visa Denied for this company</p>
        </div>
        """
        assert classify_h1b_text(html) == H1BStatus.EXPLICIT_NO


# ---------------------------------------------------------------------------
# _build_consensus — voting logic
# ---------------------------------------------------------------------------


class TestBuildConsensus:
    """Tests for the consensus voting algorithm."""

    def _make_record(self, status: H1BStatus, source: str = "test") -> H1BRecord:
        return H1BRecord(
            company_name="TestCo",
            source=source,
            status=status,
            verified_at=datetime.now(),
        )

    def test_unanimous_confirmed(self):
        """3/3 agree CONFIRMED -> CONFIRMED."""
        results = [
            self._make_record(H1BStatus.CONFIRMED, "A"),
            self._make_record(H1BStatus.CONFIRMED, "B"),
            self._make_record(H1BStatus.CONFIRMED, "C"),
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.CONFIRMED
        assert "consensus" in source

    def test_two_of_three_confirmed(self):
        """2/3 agree CONFIRMED, 1 denies -> CONFIRMED (majority wins)."""
        results = [
            self._make_record(H1BStatus.CONFIRMED, "A"),
            self._make_record(H1BStatus.EXPLICIT_NO, "B"),
            self._make_record(H1BStatus.CONFIRMED, "C"),
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.CONFIRMED
        assert "consensus" in source

    def test_two_of_three_denied(self):
        """2/3 agree EXPLICIT_NO -> EXPLICIT_NO."""
        results = [
            self._make_record(H1BStatus.EXPLICIT_NO, "A"),
            self._make_record(H1BStatus.CONFIRMED, "B"),
            self._make_record(H1BStatus.EXPLICIT_NO, "C"),
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.EXPLICIT_NO
        assert "consensus" in source

    def test_all_none(self):
        """All sources return None -> UNKNOWN."""
        results = [None, None, None]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.UNKNOWN
        assert source == "no_consensus"

    def test_one_confirmed_two_none(self):
        """1 source has data, 2 return None -> single source result."""
        results = [
            self._make_record(H1BStatus.CONFIRMED, "A"),
            None,
            None,
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.CONFIRMED
        assert "single" in source

    def test_one_confirmed_one_denied_one_none(self):
        """1 confirms, 1 denies, 1 None -> no consensus (UNKNOWN)."""
        results = [
            self._make_record(H1BStatus.CONFIRMED, "A"),
            self._make_record(H1BStatus.EXPLICIT_NO, "B"),
            None,
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.UNKNOWN
        assert source == "no_consensus"

    def test_disagreement_details_populated(self):
        """When sources disagree, details should contain all votes."""
        results = [
            self._make_record(H1BStatus.CONFIRMED, "A"),
            self._make_record(H1BStatus.EXPLICIT_NO, "B"),
            None,
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert len(details) == 3
        assert details[0]["status"] == "Confirmed"
        assert details[1]["status"] == "Explicit No"
        assert details[2]["status"] == "no_data"

    def test_two_likely_one_none(self):
        """2 sources say LIKELY -> LIKELY."""
        results = [
            self._make_record(H1BStatus.LIKELY, "A"),
            None,
            self._make_record(H1BStatus.LIKELY, "C"),
        ]
        status, source, details = _build_consensus(results, ["A", "B", "C"])
        assert status == H1BStatus.LIKELY


# ---------------------------------------------------------------------------
# _resolve_portal_tier
# ---------------------------------------------------------------------------


class TestResolvePortalTier:
    def test_tier_3_yc(self):
        company = CompanyORM(name="T", source_portal="Work at a Startup (YC)")
        assert _resolve_portal_tier(company) == PortalTier.TIER_3

    def test_tier_3_wellfound(self):
        company = CompanyORM(name="T", source_portal="Wellfound")
        assert _resolve_portal_tier(company) == PortalTier.TIER_3

    def test_tier_1_linkedin(self):
        company = CompanyORM(name="T", source_portal="LinkedIn")
        assert _resolve_portal_tier(company) == PortalTier.TIER_1

    def test_tier_2_default(self):
        company = CompanyORM(name="T", source_portal="Greenhouse")
        assert _resolve_portal_tier(company) == PortalTier.TIER_2

    def test_unknown_portal_defaults_tier_2(self):
        company = CompanyORM(name="T", source_portal="SomeNewPortal")
        assert _resolve_portal_tier(company) == PortalTier.TIER_2


# ---------------------------------------------------------------------------
# H1BVerifier.verify — integration tests with mocked clients
# ---------------------------------------------------------------------------


class TestH1BVerifier:
    """Tests for the H1BVerifier orchestrator."""

    def _make_company(self, name: str = "TestCo", portal: str = "Greenhouse") -> CompanyORM:
        c = CompanyORM(name=name, source_portal=portal)
        c.id = 42
        return c

    def _make_tier3_company(self, name: str = "YCCo") -> CompanyORM:
        c = CompanyORM(name=name, source_portal="Work at a Startup (YC)")
        c.id = 99
        return c

    @pytest.mark.asyncio
    async def test_tier3_auto_pass(self):
        """Tier 3 companies get NOT_APPLICABLE without querying sources."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock()
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock()
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock()

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        company = self._make_tier3_company()
        result = await verifier.verify(company)

        assert result.status == H1BStatus.NOT_APPLICABLE
        assert result.source == "auto_pass"
        # No sources should have been called
        froghire.search.assert_not_called()
        h1bgrader.search.assert_not_called()
        myvisajobs.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_sources_confirm(self):
        """All 3 sources return CONFIRMED -> consensus CONFIRMED."""
        record = H1BRecord(
            company_name="TestCo",
            status=H1BStatus.CONFIRMED,
            source="test",
            lca_count=10,
            verified_at=datetime.now(),
        )

        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="Frog Hire", lca_count=10, verified_at=datetime.now(),
        ))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="H1BGrader", lca_count=8, verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="MyVisaJobs", lca_count=12, verified_at=datetime.now(),
        ))

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        company = self._make_company()
        result = await verifier.verify(company)

        assert result.status == H1BStatus.CONFIRMED
        assert "consensus" in result.source
        assert result.company_id == 42

    @pytest.mark.asyncio
    async def test_two_confirm_one_denies(self):
        """2/3 CONFIRMED, 1 EXPLICIT_NO -> CONFIRMED (majority wins)."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="Frog Hire", verified_at=datetime.now(),
        ))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.EXPLICIT_NO,
            source="H1BGrader", verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="MyVisaJobs", verified_at=datetime.now(),
        ))

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_all_sources_fail(self):
        """All 3 sources return None -> UNKNOWN."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=None)
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=None)
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.UNKNOWN
        assert result.source == "all_sources_empty"

    @pytest.mark.asyncio
    async def test_one_source_exception_others_confirm(self):
        """One source raises exception, other 2 confirm -> CONFIRMED."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(side_effect=RuntimeError("Connection timeout"))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="H1BGrader", verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="MyVisaJobs", verified_at=datetime.now(),
        ))

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_all_sources_raise_exceptions(self):
        """All 3 sources raise exceptions -> UNKNOWN."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(side_effect=RuntimeError("fail"))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(side_effect=TimeoutError("timeout"))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(side_effect=ConnectionError("down"))

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.UNKNOWN
        assert result.source == "all_sources_empty"

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """Verify all 3 sources are queried concurrently, not sequentially."""
        call_order = []

        async def slow_froghire(name):
            call_order.append(("froghire_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            call_order.append(("froghire_end", asyncio.get_event_loop().time()))
            return H1BRecord(
                company_name=name, status=H1BStatus.CONFIRMED,
                source="Frog Hire", verified_at=datetime.now(),
            )

        async def slow_h1bgrader(name):
            call_order.append(("h1bgrader_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            call_order.append(("h1bgrader_end", asyncio.get_event_loop().time()))
            return H1BRecord(
                company_name=name, status=H1BStatus.CONFIRMED,
                source="H1BGrader", verified_at=datetime.now(),
            )

        async def slow_myvisajobs(name):
            call_order.append(("myvisajobs_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.05)
            call_order.append(("myvisajobs_end", asyncio.get_event_loop().time()))
            return H1BRecord(
                company_name=name, status=H1BStatus.CONFIRMED,
                source="MyVisaJobs", verified_at=datetime.now(),
            )

        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = slow_froghire
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = slow_h1bgrader
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = slow_myvisajobs

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        # All 3 starts should happen before any end (parallel execution)
        starts = [t for name, t in call_order if name.endswith("_start")]
        ends = [t for name, t in call_order if name.endswith("_end")]

        assert len(starts) == 3
        assert len(ends) == 3

        # The latest start should be before the earliest end (proves parallelism)
        latest_start = max(starts)
        earliest_end = min(ends)
        assert latest_start < earliest_end, (
            f"Sources not running in parallel: latest_start={latest_start}, "
            f"earliest_end={earliest_end}"
        )

    @pytest.mark.asyncio
    async def test_disagreement_one_confirm_one_deny_one_none(self):
        """1 confirm + 1 deny + 1 None -> UNKNOWN (no majority)."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="Frog Hire", verified_at=datetime.now(),
        ))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.EXPLICIT_NO,
            source="H1BGrader", verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.UNKNOWN
        assert result.source == "no_consensus"

    @pytest.mark.asyncio
    async def test_single_source_with_data(self):
        """Only 1 source returns data, other 2 None -> uses single source."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=None)
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="TestCo", status=H1BStatus.CONFIRMED,
            source="H1BGrader", lca_count=5, verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        result = await verifier.verify(self._make_company())

        assert result.status == H1BStatus.CONFIRMED
        assert "single" in result.source
        assert result.lca_count == 5

    @pytest.mark.asyncio
    async def test_batch_verify_calls_verify_for_each(self):
        """batch_verify should call verify for each company."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="Co", status=H1BStatus.CONFIRMED,
            source="Frog Hire", verified_at=datetime.now(),
        ))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="Co", status=H1BStatus.CONFIRMED,
            source="H1BGrader", verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        companies = [self._make_company(f"Co{i}") for i in range(3)]

        results = await verifier.batch_verify(companies)

        assert len(results) == 3
        assert all(r.status == H1BStatus.CONFIRMED for r in results)

    @pytest.mark.asyncio
    async def test_batch_verify_persists_to_session(self, session):
        """batch_verify with session should persist H1BORM records."""
        froghire = MagicMock(spec=FrogHireClient)
        froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="PersistCo", status=H1BStatus.CONFIRMED,
            source="Frog Hire", lca_count=15, verified_at=datetime.now(),
        ))
        h1bgrader = MagicMock(spec=H1BGraderClient)
        h1bgrader.search = AsyncMock(return_value=H1BRecord(
            company_name="PersistCo", status=H1BStatus.CONFIRMED,
            source="H1BGrader", verified_at=datetime.now(),
        ))
        myvisajobs = MagicMock(spec=MyVisaJobsClient)
        myvisajobs.search = AsyncMock(return_value=None)

        # Create a real company in the DB
        company = CompanyORM(name="PersistCo", source_portal="Greenhouse", stage="To apply")
        session.add(company)
        session.flush()

        verifier = H1BVerifier(froghire=froghire, h1bgrader=h1bgrader, myvisajobs=myvisajobs)
        results = await verifier.batch_verify([company], session=session)

        assert len(results) == 1
        assert results[0].status == H1BStatus.CONFIRMED

        # Verify ORM was persisted
        from src.db.orm import H1BORM
        h1b_records = session.query(H1BORM).all()
        assert len(h1b_records) == 1
        assert h1b_records[0].status == "Confirmed"

        # Verify company was updated
        session.refresh(company)
        assert company.h1b_status == "Confirmed"


# ---------------------------------------------------------------------------
# FrogHireClient._parse_result — regex via classify_h1b_text
# ---------------------------------------------------------------------------


class TestFrogHireParseResult:
    """Tests for FrogHireClient HTML parsing."""

    def test_confirmed_status(self):
        client = FrogHireClient()
        html = '<div>H1B Sponsor: Yes</div><div>LCA: 25</div>'
        record = client._parse_result("Acme", html)
        assert record is not None
        assert record.status == H1BStatus.CONFIRMED

    def test_denied_not_false_positive(self):
        """Ensure 'H1B Visa Denied' does NOT get classified as CONFIRMED."""
        client = FrogHireClient()
        html = '<div>H1B Visa Denied</div>'
        record = client._parse_result("Acme", html)
        # Should return a record with EXPLICIT_NO (since it's meaningful data)
        assert record is not None
        assert record.status == H1BStatus.EXPLICIT_NO

    def test_no_results_returns_none(self):
        client = FrogHireClient()
        html = '<div>No companies found</div>'
        record = client._parse_result("Acme", html)
        assert record is None

    def test_extracts_lca_count(self):
        client = FrogHireClient()
        html = '<div>H1B Sponsor: Yes</div><div>LCA: 42</div>'
        record = client._parse_result("Acme", html)
        assert record is not None
        assert record.lca_count == 42

    def test_extracts_perm(self):
        client = FrogHireClient()
        html = '<div>H1B Sponsor: Yes</div><div>PERM Approved</div>'
        record = client._parse_result("Acme", html)
        assert record is not None
        assert record.has_perm is True

    def test_extracts_everify(self):
        client = FrogHireClient()
        html = '<div>H1B Sponsor: Yes</div><div>E-Verify Enrolled</div>'
        record = client._parse_result("Acme", html)
        assert record is not None
        assert record.has_everify is True

    def test_unknown_no_meaningful_data_returns_none(self):
        """If status is UNKNOWN and no other data, return None."""
        client = FrogHireClient()
        html = '<div>Some company page with no H1B info</div>'
        record = client._parse_result("Acme", html)
        assert record is None
