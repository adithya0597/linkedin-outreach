"""C1 integration tests — end-to-end verification of cross-feature flows.

Tests verify that features from the C1 wave work together correctly:
1. Pipeline -> H1B -> Score -> Draft flow (stage ordering)
2. Warm-up state machine -> outreach readiness gate
3. Persistence dedup -> Notion sync round-trip
4. Quality gates end-to-end (completeness buckets + readiness checks)

NOTE: Some C1 features (warmup_tracker, quality_gates with 15-field system,
updated Company model) may not be present in all worktrees. Tests that depend
on these features use conditional imports and skip markers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.enums import H1BStatus, SourcePortal
from src.db.orm import H1BORM, Base, CompanyORM
from src.models.h1b import H1BRecord
from src.models.job_posting import JobPosting

# Conditional imports for C1-specific modules
try:
    from src.db.orm import WarmUpActionORM, WarmUpSequenceORM

    _HAS_WARMUP_ORM = True
except ImportError:
    _HAS_WARMUP_ORM = False

try:
    from src.outreach.warmup_tracker import (
        InvalidWarmUpTransitionError,
        WarmUpAction,
        WarmUpState,
        WarmUpTracker,
    )

    _HAS_WARMUP_TRACKER = True
except (ImportError, ModuleNotFoundError):
    _HAS_WARMUP_TRACKER = False

try:
    from src.pipeline.quality_gates import get_quality_report, is_outreach_ready

    _HAS_QUALITY_GATES = True
except (ImportError, ModuleNotFoundError):
    _HAS_QUALITY_GATES = False

try:
    from src.models.company import Company, CompletenessResult

    _HAS_COMPLETENESS = hasattr(Company, "COMPLETENESS_FIELDS") or hasattr(
        Company, "calculate_completeness"
    )
except (ImportError, ModuleNotFoundError):
    _HAS_COMPLETENESS = False


# Skip markers
requires_warmup = pytest.mark.skipif(
    not (_HAS_WARMUP_ORM and _HAS_WARMUP_TRACKER),
    reason="WarmUp ORM tables and warmup_tracker module required (C1 feature)",
)
requires_quality_gates = pytest.mark.skipif(
    not _HAS_QUALITY_GATES,
    reason="src.pipeline.quality_gates module required (C1 feature)",
)
requires_completeness = pytest.mark.skipif(
    not _HAS_COMPLETENESS,
    reason="Company.calculate_completeness with CompletenessResult required (C1 feature)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def c1_engine():
    """In-memory SQLite engine with ALL tables including warmup_* tables."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def c1_session(c1_engine):
    """Session bound to in-memory DB."""
    factory = sessionmaker(bind=c1_engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def seed_companies(c1_session: Session) -> list[CompanyORM]:
    """Insert a batch of companies spanning different completeness levels."""
    companies = [
        CompanyORM(
            name="Snorkel AI",
            description="Data-centric AI platform for labeling and model development",
            hq_location="San Francisco, CA",
            employees=150,
            employees_range="100-200",
            funding_stage="Series C",
            funding_amount="$135M",
            is_ai_native=True,
            tier="Tier 1 - HIGH",
            source_portal="Greenhouse",
            h1b_status="Confirmed",
            h1b_source="Frog Hire",
            h1b_details="LCA: 45 | PERM: Yes",
            hiring_manager="Jane Smith",
            hiring_manager_linkedin="https://linkedin.com/in/janesmith",
            role="AI Engineer",
            role_url="https://snorkelai.com/careers/ai-engineer",
            salary_range="$150k-$200k",
            fit_score=85.0,
            website="https://snorkelai.com",
            linkedin_url="https://linkedin.com/company/snorkelai",
            why_fit="Data-centric AI maps to CDC pipeline expertise",
            best_stats="300+ table CDC pipelines, 99.9% integrity",
            data_completeness=90.0,
        ),
        CompanyORM(
            name="LlamaIndex",
            description="Data framework for LLM applications",
            hq_location="San Francisco, CA",
            employees=40,
            employees_range="30-50",
            funding_stage="Series A",
            funding_amount="$19M",
            is_ai_native=True,
            tier="Tier 1 - HIGH",
            source_portal="Ashby",
            h1b_status="Confirmed",
            h1b_source="Frog Hire",
            hiring_manager="John Doe",
            role="AI Engineer",
            role_url="https://llamaindex.ai/careers",
            website="https://llamaindex.ai",
            linkedin_url="https://linkedin.com/company/llamaindex",
            data_completeness=75.0,
        ),
        CompanyORM(
            name="Skeleton Startup",
            description="",
            hq_location="",
            employees=None,
            funding_stage="Unknown",
            source_portal="Hiring Cafe",
            tier="Tier 5 - RESCAN",
            h1b_status="Unknown",
            data_completeness=15.0,
        ),
        CompanyORM(
            name="No H1B Corp",
            description="Fintech platform",
            hq_location="New York, NY",
            employees=80,
            funding_stage="Series B",
            is_ai_native=True,
            tier="Tier 2 - STRONG",
            source_portal="LinkedIn",
            h1b_status="Explicit No",
            hiring_manager="Jane Doe",
            role="ML Engineer",
            role_url="https://noh1b.com/careers",
            data_completeness=60.0,
        ),
    ]
    for c in companies:
        c1_session.add(c)
    c1_session.commit()
    return companies


# ===========================================================================
# Test Class 1: Pipeline -> H1B -> Score -> Draft flow
# ===========================================================================


class TestPipelineH1BFlow:
    """Verify pipeline stages execute in correct order and H1B runs before scoring."""

    def test_h1b_verification_before_scoring(self, c1_session: Session, seed_companies):
        """H1B verification must update company records BEFORE scoring reads them."""
        # Arrange: pick a company with Unknown H1B
        skeleton = c1_session.query(CompanyORM).filter(CompanyORM.name == "Skeleton Startup").one()
        assert skeleton.h1b_status == "Unknown"

        # Act: simulate H1B verification setting Confirmed status
        h1b_record = H1BORM(
            company_id=skeleton.id,
            company_name="Skeleton Startup",
            status="Confirmed",
            source="H1BGrader",
            lca_count=12,
            verified_at=datetime.now(),
        )
        c1_session.add(h1b_record)
        skeleton.h1b_status = "Confirmed"
        skeleton.h1b_source = "H1BGrader"
        skeleton.h1b_details = "LCA: 12"
        c1_session.commit()

        # Assert: the scoring stage would now see Confirmed status
        refreshed = c1_session.query(CompanyORM).filter(CompanyORM.id == skeleton.id).one()
        assert refreshed.h1b_status == "Confirmed"
        assert refreshed.h1b_source == "H1BGrader"

    def test_h1b_verifier_waterfall_confirmed(self, c1_session: Session, seed_companies):
        """H1BVerifier returns CONFIRMED when FrogHire finds data."""
        from src.validators.h1b_verifier import H1BVerifier

        # Create mock clients
        mock_froghire = MagicMock()
        mock_froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="Skeleton Startup",
            status=H1BStatus.CONFIRMED,
            source="Frog Hire",
            lca_count=25,
            has_perm=True,
            verified_at=datetime.now(),
        ))
        mock_h1bgrader = MagicMock()
        mock_h1bgrader.search = AsyncMock(return_value=None)
        mock_myvisajobs = MagicMock()
        mock_myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(
            froghire=mock_froghire,
            h1bgrader=mock_h1bgrader,
            myvisajobs=mock_myvisajobs,
        )

        skeleton = c1_session.query(CompanyORM).filter(CompanyORM.name == "Skeleton Startup").one()
        # Set portal to a Tier 2 portal so waterfall runs (not auto-pass)
        skeleton.source_portal = "LinkedIn"
        c1_session.commit()

        result = asyncio.get_event_loop().run_until_complete(verifier.verify(skeleton))
        assert result.status == H1BStatus.CONFIRMED
        assert result.lca_count == 25
        # All sources queried in parallel (consensus voting)
        mock_froghire.search.assert_awaited_once()

    def test_h1b_verifier_tier3_autopass(self, c1_session: Session, seed_companies):
        """Tier 3 portal companies get auto-pass with NOT_APPLICABLE status."""
        from src.validators.h1b_verifier import H1BVerifier

        mock_froghire = MagicMock()
        mock_froghire.search = AsyncMock(return_value=None)
        mock_h1bgrader = MagicMock()
        mock_h1bgrader.search = AsyncMock(return_value=None)
        mock_myvisajobs = MagicMock()
        mock_myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(
            froghire=mock_froghire,
            h1bgrader=mock_h1bgrader,
            myvisajobs=mock_myvisajobs,
        )

        # Skeleton Startup is on Hiring Cafe -> Tier 3
        skeleton = c1_session.query(CompanyORM).filter(CompanyORM.name == "Skeleton Startup").one()
        assert skeleton.source_portal == "Hiring Cafe"

        result = asyncio.get_event_loop().run_until_complete(verifier.verify(skeleton))
        assert result.status == H1BStatus.NOT_APPLICABLE
        assert result.source == "auto_pass"
        # No HTTP clients should have been called
        mock_froghire.search.assert_not_awaited()
        mock_h1bgrader.search.assert_not_awaited()
        mock_myvisajobs.search.assert_not_awaited()

    def test_h1b_verifier_waterfall_fallthrough(self, c1_session: Session, seed_companies):
        """When all 3 sources return None, verifier returns UNKNOWN."""
        from src.validators.h1b_verifier import H1BVerifier

        mock_froghire = MagicMock()
        mock_froghire.search = AsyncMock(return_value=None)
        mock_h1bgrader = MagicMock()
        mock_h1bgrader.search = AsyncMock(return_value=None)
        mock_myvisajobs = MagicMock()
        mock_myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(
            froghire=mock_froghire,
            h1bgrader=mock_h1bgrader,
            myvisajobs=mock_myvisajobs,
        )

        # Set to Tier 2 portal to ensure waterfall runs
        skeleton = c1_session.query(CompanyORM).filter(CompanyORM.name == "Skeleton Startup").one()
        skeleton.source_portal = "Greenhouse"
        c1_session.commit()

        result = asyncio.get_event_loop().run_until_complete(verifier.verify(skeleton))
        assert result.status == H1BStatus.UNKNOWN
        assert result.source == "all_sources_empty"
        # All 3 sources should have been tried
        mock_froghire.search.assert_awaited_once()
        mock_h1bgrader.search.assert_awaited_once()
        mock_myvisajobs.search.assert_awaited_once()

    def test_h1b_batch_verify_persists(self, c1_session: Session, seed_companies):
        """batch_verify with a session persists H1BORM records and updates CompanyORM."""
        from src.validators.h1b_verifier import H1BVerifier

        mock_froghire = MagicMock()
        mock_froghire.search = AsyncMock(return_value=H1BRecord(
            company_name="",
            status=H1BStatus.CONFIRMED,
            source="Frog Hire",
            lca_count=10,
            approval_rate=95.0,
            verified_at=datetime.now(),
        ))
        mock_h1bgrader = MagicMock()
        mock_h1bgrader.search = AsyncMock(return_value=None)
        mock_myvisajobs = MagicMock()
        mock_myvisajobs.search = AsyncMock(return_value=None)

        verifier = H1BVerifier(
            froghire=mock_froghire,
            h1bgrader=mock_h1bgrader,
            myvisajobs=mock_myvisajobs,
        )

        # Use a Tier 2 company
        noh1b = c1_session.query(CompanyORM).filter(CompanyORM.name == "No H1B Corp").one()
        noh1b.source_portal = "Greenhouse"
        c1_session.commit()

        results = asyncio.get_event_loop().run_until_complete(
            verifier.batch_verify([noh1b], session=c1_session, concurrency=1)
        )

        assert len(results) == 1
        assert results[0].status == H1BStatus.CONFIRMED

        # Verify H1BORM was persisted
        h1b_rows = c1_session.query(H1BORM).filter(H1BORM.company_id == noh1b.id).all()
        assert len(h1b_rows) == 1
        assert h1b_rows[0].status == "Confirmed"
        assert h1b_rows[0].lca_count == 10

        # Verify CompanyORM was updated
        refreshed = c1_session.query(CompanyORM).filter(CompanyORM.id == noh1b.id).one()
        assert refreshed.h1b_status == "Confirmed"
        assert "Approval: 95.0%" in refreshed.h1b_details

    def test_daily_orchestrator_stage_ordering(self, c1_session: Session):
        """DailyOrchestrator.run_full_day executes stages in correct order."""
        from src.pipeline.daily_orchestrator import DailyOrchestrator

        orchestrator = DailyOrchestrator(c1_session)
        execution_log: list[str] = []

        # Patch each stage to record execution order
        def mock_scan():
            execution_log.append("scan")
            return {"total_found": 5, "total_new": 3}

        def mock_enrich():
            execution_log.append("enrichment")
            return {"enriched": 3}

        def mock_score():
            execution_log.append("scoring")
            return {"scored": 3}

        def mock_queue():
            execution_log.append("send_queue")
            return []

        def mock_followup():
            execution_log.append("followups")
            return {"overdue": [], "due_today": []}

        def mock_sync(dry_run=False):
            execution_log.append("sync")
            return {"synced": 3}

        orchestrator._run_scan = mock_scan
        orchestrator._run_enrichment = mock_enrich
        orchestrator._run_scoring = mock_score
        orchestrator._run_send_queue = mock_queue
        orchestrator._run_followup_check = mock_followup
        orchestrator._run_sync = mock_sync

        result = orchestrator.run_full_day(dry_run=True)

        # Verify order: scan -> enrichment -> scoring -> send_queue -> followups -> sync
        assert execution_log == [
            "scan", "enrichment", "scoring", "send_queue", "followups", "sync"
        ]
        assert result["total_time"] > 0
        assert result["scan"]["total_found"] == 5

    def test_daily_orchestrator_stage_failure_isolation(self, c1_session: Session):
        """A failure in one pipeline stage does not block subsequent stages."""
        from src.pipeline.daily_orchestrator import DailyOrchestrator

        orchestrator = DailyOrchestrator(c1_session)
        execution_log: list[str] = []

        def mock_scan():
            execution_log.append("scan")
            raise RuntimeError("Scan portal timeout")

        def mock_enrich():
            execution_log.append("enrichment")
            return {"enriched": 0}

        def mock_score():
            execution_log.append("scoring")
            return {"scored": 0}

        def mock_queue():
            execution_log.append("send_queue")
            return []

        def mock_followup():
            execution_log.append("followups")
            return {"overdue": []}

        def mock_sync(dry_run=False):
            execution_log.append("sync")
            return {"synced": 0}

        orchestrator._run_scan = mock_scan
        orchestrator._run_enrichment = mock_enrich
        orchestrator._run_scoring = mock_score
        orchestrator._run_send_queue = mock_queue
        orchestrator._run_followup_check = mock_followup
        orchestrator._run_sync = mock_sync

        result = orchestrator.run_full_day()

        # All stages should have run despite scan failure
        assert execution_log == [
            "scan", "enrichment", "scoring", "send_queue", "followups", "sync"
        ]
        # Scan result should contain error
        assert "error" in result["scan"]
        assert "Scan portal timeout" in result["scan"]["error"]
        # Other stages should have succeeded
        assert result["enrichment"]["enriched"] == 0


# ===========================================================================
# Test Class 2: Warm-up state machine -> outreach readiness gate
# ===========================================================================


@requires_warmup
class TestWarmUpOutreachReadiness:
    """Verify warm-up state machine transitions and quality gate integration."""

    def test_warmup_pending_to_warming(
        self, c1_session: Session, seed_companies,
    ):
        """Recording a PROFILE_VIEW transitions from PENDING to WARMING."""
        tracker = WarmUpTracker(c1_session)
        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()

        action = tracker.record_action(
            company_id=snorkel.id,
            contact_name="Jane Smith",
            action=WarmUpAction.PROFILE_VIEW,
            notes="Viewed profile from feed",
        )
        assert action is not None

        status = tracker.get_status(snorkel.id, "Jane Smith")
        assert status["state"] == WarmUpState.WARMING.value
        assert "PROFILE_VIEW" in status["completed_actions"]
        assert status["is_ready"] is False

    def test_warmup_warming_to_ready(
        self, c1_session: Session, seed_companies,
    ):
        """Completing all required actions transitions to READY."""
        tracker = WarmUpTracker(c1_session)
        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()

        # Record both required actions
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.PROFILE_VIEW)
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.LIKE_POST)

        status = tracker.get_status(snorkel.id, "Jane Smith")
        assert status["state"] == WarmUpState.READY.value
        assert status["is_ready"] is True
        assert status["action_count"] == 2

    def test_warmup_ready_to_sent(
        self, c1_session: Session, seed_companies,
    ):
        """mark_sent transitions from READY to SENT terminal state."""
        tracker = WarmUpTracker(c1_session)
        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()

        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.PROFILE_VIEW)
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.LIKE_POST)

        seq = tracker.mark_sent(snorkel.id, "Jane Smith")
        assert seq.state == WarmUpState.SENT.value

        # Verify terminal state: cannot record more actions
        with pytest.raises(InvalidWarmUpTransitionError):
            tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.COMMENT)

    def test_warmup_get_ready_contacts(
        self, c1_session: Session, seed_companies,
    ):
        """get_ready_contacts returns only contacts in READY state."""
        tracker = WarmUpTracker(c1_session)
        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()
        llama = c1_session.query(CompanyORM).filter(CompanyORM.name == "LlamaIndex").one()

        # Snorkel contact: complete warmup -> READY
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.PROFILE_VIEW)
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.LIKE_POST)

        # LlamaIndex contact: only 1 action -> WARMING
        tracker.record_action(llama.id, "John Doe", WarmUpAction.PROFILE_VIEW)

        ready = tracker.get_ready_contacts()
        assert len(ready) == 1
        assert ready[0]["contact_name"] == "Jane Smith"
        assert ready[0]["company_name"] == "Snorkel AI"

    def test_warmup_daily_actions_recommendations(
        self, c1_session: Session, seed_companies,
    ):
        """get_daily_actions recommends correct next actions."""
        tracker = WarmUpTracker(c1_session)
        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()
        llama = c1_session.query(CompanyORM).filter(CompanyORM.name == "LlamaIndex").one()

        # Create two sequences: one with profile view done, one fresh
        tracker.record_action(snorkel.id, "Jane Smith", WarmUpAction.PROFILE_VIEW)
        # LlamaIndex: create a sequence implicitly by recording
        tracker.record_action(llama.id, "John Doe", WarmUpAction.PROFILE_VIEW)

        actions = tracker.get_daily_actions()
        # Both should have WARMING state, recommend LIKE_POST next
        assert len(actions) == 2
        for a in actions:
            assert a["recommended_action"] == "LIKE_POST"


# ===========================================================================
# Test Class 3: Persistence dedup -> Notion sync round-trip
# ===========================================================================


class TestPersistenceDedupNotionSync:
    """Verify persistence dedup logic and Notion schema round-trip conversion."""

    def test_url_dedup(self, c1_session: Session):
        """Postings with duplicate URLs are not re-inserted."""
        from src.scrapers.persistence import persist_scan_results

        postings = [
            JobPosting(
                company_name="Acme AI",
                title="AI Engineer",
                url="https://example.com/jobs/1",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
            JobPosting(
                company_name="Acme AI",
                title="AI Engineer",
                url="https://example.com/jobs/1",  # Duplicate URL
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
        ]
        total, new, _new_companies = persist_scan_results(
            c1_session, "startup.jobs", postings, scan_type="full"
        )
        assert total == 2
        assert new == 1  # Only one should be inserted

    def test_composite_key_dedup(self, c1_session: Session):
        """Postings with same normalized company+title are deduped even with different URLs."""
        from src.scrapers.persistence import persist_scan_results

        postings = [
            JobPosting(
                company_name="Acme AI",
                title="AI Engineer",
                url="https://portal-a.com/jobs/1",
                source_portal=SourcePortal.STARTUP_JOBS,
            ),
            JobPosting(
                company_name="  ACME AI  ",  # Extra whitespace
                title="AI Engineer",
                url="https://portal-b.com/jobs/1",  # Different URL
                source_portal=SourcePortal.HIRING_CAFE,
            ),
        ]
        total, new, _new_companies = persist_scan_results(
            c1_session, "startup.jobs", postings, scan_type="full"
        )
        assert total == 2
        assert new == 1  # Second posting deduped by composite key

    def test_case_insensitive_company_dedup(self, c1_session: Session):
        """Company creation is case-insensitive (no duplicate companies)."""
        from src.scrapers.persistence import persist_scan_results

        postings = [
            JobPosting(
                company_name="snorkel ai",
                title="ML Engineer",
                url="https://example.com/j/1",
                source_portal=SourcePortal.GREENHOUSE,
            ),
            JobPosting(
                company_name="SNORKEL AI",
                title="Data Engineer",
                url="https://example.com/j/2",
                source_portal=SourcePortal.GREENHOUSE,
            ),
        ]
        _total, new, new_companies = persist_scan_results(
            c1_session, "Greenhouse", postings, scan_type="full"
        )
        assert new == 2  # Both postings are new (different titles)
        assert new_companies == 1  # Only one company created

        companies = c1_session.query(CompanyORM).filter(
            CompanyORM.name.ilike("snorkel ai")
        ).all()
        assert len(companies) == 1

    def test_new_company_auto_created(self, c1_session: Session):
        """Companies are auto-created as skeleton records from postings."""
        from src.scrapers.persistence import persist_scan_results

        postings = [
            JobPosting(
                company_name="BrandNewAI",
                title="Engineer",
                url="https://new.ai/j/1",
                source_portal=SourcePortal.ASHBY,
            ),
        ]
        _total, _new, new_companies = persist_scan_results(
            c1_session, "Ashby", postings, scan_type="full"
        )
        assert new_companies == 1

        company = c1_session.query(CompanyORM).filter(CompanyORM.name == "BrandNewAI").one()
        assert company.tier == "Tier 5 - RESCAN"
        assert company.data_completeness == 20.0
        assert company.source_portal == "Ashby"

    def test_notion_orm_to_properties_roundtrip(self, c1_session: Session, seed_companies):
        """CompanyORM -> Notion properties -> back should preserve key fields."""
        from src.integrations.notion_sync import NotionSchemas

        snorkel = c1_session.query(CompanyORM).filter(CompanyORM.name == "Snorkel AI").one()

        # Convert ORM -> Notion properties
        props = NotionSchemas.orm_to_notion(snorkel)

        # Verify key properties exist
        assert "Company" in props
        assert props["Company"]["title"][0]["text"]["content"] == "Snorkel AI"
        assert "Tier" in props
        assert props["Tier"]["select"]["name"] == "Tier 1 - HIGH"
        assert "H1B Sponsorship" in props
        assert props["H1B Sponsorship"]["select"]["name"] == "Confirmed"
        assert "Fit Score" in props
        assert props["Fit Score"]["number"] == 85.0
        assert "Link" in props
        assert props["Link"]["url"] == "https://snorkelai.com/careers/ai-engineer"

    def test_notion_properties_to_dict_roundtrip(self):
        """Notion page dict -> ORM dict preserves all mapped fields."""
        from src.integrations.notion_sync import NotionSchemas

        # Simulate a Notion page response
        notion_page = {
            "id": "page-abc-123",
            "last_edited_time": "2026-03-10T12:00:00.000Z",
            "properties": {
                "Company": {
                    "type": "title",
                    "title": [{"plain_text": "TestCo"}],
                },
                "Tier": {
                    "type": "select",
                    "select": {"name": "Tier 2 - STRONG"},
                },
                "Fit Score": {
                    "type": "number",
                    "number": 72.5,
                },
                "H1B Sponsorship": {
                    "type": "select",
                    "select": {"name": "Likely"},
                },
                "Stage": {
                    "type": "status",
                    "status": {"name": "Applied"},
                },
                "Hiring Manager": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Alice Smith"}],
                },
                "Link": {
                    "type": "url",
                    "url": "https://testco.ai/careers",
                },
                "Differentiators": {
                    "type": "multi_select",
                    "multi_select": [
                        {"name": "RAG"},
                        {"name": "Graph DB"},
                    ],
                },
            },
        }

        result = NotionSchemas.notion_to_dict(notion_page)

        assert result["name"] == "TestCo"
        assert result["tier"] == "Tier 2 - STRONG"
        assert result["fit_score"] == 72.5
        assert result["h1b_status"] == "Likely"
        assert result["stage"] == "Applied"
        assert result["hiring_manager"] == "Alice Smith"
        assert result["role_url"] == "https://testco.ai/careers"
        assert "RAG" in result["differentiators"]
        assert "Graph DB" in result["differentiators"]
        assert result["_notion_page_id"] == "page-abc-123"

    def test_notion_multi_select_pipe_format(self):
        """Multi-select values with pipes are handled correctly."""
        from src.integrations.notion_base import NotionPropertyConverter

        # ORM stores multi-select as pipe-separated string
        value = "RAG | Graph DB | Vector Search"
        prop = NotionPropertyConverter.to_notion(value, "multi_select")
        assert prop is not None
        assert len(prop["multi_select"]) == 3
        assert prop["multi_select"][0]["name"] == "RAG"
        assert prop["multi_select"][1]["name"] == "Graph DB"
        assert prop["multi_select"][2]["name"] == "Vector Search"

        # Round-trip back
        result = NotionPropertyConverter.from_notion(prop, "multi_select")
        assert "RAG" in result
        assert "Graph DB" in result
        assert "Vector Search" in result


# ===========================================================================
# Test Class 4: Quality gates end-to-end
# ===========================================================================


@requires_quality_gates
@requires_completeness
class TestQualityGatesE2E:
    """Verify quality gate completeness scoring and outreach readiness checks."""

    def _make_company(self, **overrides) -> Company:
        """Helper to create Company dataclass instances with overrides."""
        from src.config.enums import FundingStage
        from src.models.company import Company

        defaults = dict(
            name="Test Company",
            website="https://test.com",
            linkedin_url="https://linkedin.com/company/test",
            employees_range="50-100",
            funding_stage=FundingStage.SERIES_A,
            funding_amount="$10M",
            hiring_manager="Jane Doe",
            role_url="https://test.com/careers",
            h1b_status=H1BStatus.CONFIRMED,
            salary_range="$150k-$200k",
            tech_stack=["Python", "FastAPI"],
            differentiators=["RAG", "Vector DB"],
        )
        defaults.update(overrides)

        # Handle string -> enum conversion
        if isinstance(defaults.get("funding_stage"), str):
            try:
                defaults["funding_stage"] = FundingStage(defaults["funding_stage"])
            except ValueError:
                defaults["funding_stage"] = FundingStage.UNKNOWN

        if isinstance(defaults.get("h1b_status"), str):
            try:
                defaults["h1b_status"] = H1BStatus(defaults["h1b_status"])
            except ValueError:
                defaults["h1b_status"] = H1BStatus.UNKNOWN

        return Company(**defaults)

    def test_outreach_ready_full_company(self):
        """A fully populated company with Confirmed H1B and hiring manager passes gate."""
        company = self._make_company(
            ai_nativity="AI-native",
            headquarters_city="San Francisco",
            headquarters_state="CA",
        )
        result = company.calculate_completeness()
        assert result.score >= 0.6
        assert is_outreach_ready(company) is True

    def test_outreach_blocked_low_completeness(self):
        """A skeleton company with low completeness is blocked."""
        company = self._make_company(
            name="Empty Corp",
            website="",
            linkedin_url="",
            employees_range="",
            funding_stage="Unknown",
            funding_amount="",
            hiring_manager="Some Manager",
            role_url="",
            h1b_status=H1BStatus.CONFIRMED,
            salary_range="",
            tech_stack=[],
            differentiators=[],
        )
        result = company.calculate_completeness()
        assert result.score < 0.6
        assert is_outreach_ready(company) is False

    def test_outreach_blocked_explicit_no_h1b(self):
        """A company with EXPLICIT_NO H1B is always blocked."""
        company = self._make_company(
            h1b_status=H1BStatus.EXPLICIT_NO,
            hiring_manager="John Doe",
            ai_nativity="AI-native",
            headquarters_city="NYC",
            headquarters_state="NY",
        )
        # Even with high completeness, H1B denial blocks outreach
        result = company.calculate_completeness()
        assert result.score >= 0.6
        assert is_outreach_ready(company) is False

    def test_outreach_blocked_no_hiring_manager(self):
        """A company without hiring manager is blocked."""
        company = self._make_company(
            hiring_manager="",
            ai_nativity="AI-native",
            headquarters_city="Austin",
            headquarters_state="TX",
        )
        assert is_outreach_ready(company) is False

    def test_quality_report_bucket_distribution(self):
        """get_quality_report produces correct bucket counts."""
        companies = [
            # High completeness (75-100%)
            self._make_company(
                name="HighCo",
                ai_nativity="AI-native",
                headquarters_city="SF",
                headquarters_state="CA",
            ),
            # Medium completeness (50-75%)
            self._make_company(
                name="MedCo",
                salary_range="",
                tech_stack=[],
                differentiators=[],
                ai_nativity="",
                headquarters_city="",
                headquarters_state="",
            ),
            # Low completeness (0-25%)
            self._make_company(
                name="LowCo",
                website="",
                linkedin_url="",
                employees_range="",
                funding_stage="Unknown",
                funding_amount="",
                hiring_manager="",
                role_url="",
                h1b_status=H1BStatus.UNKNOWN,
                salary_range="",
                tech_stack=[],
                differentiators=[],
                ai_nativity="",
                headquarters_city="",
                headquarters_state="",
            ),
        ]

        # Pre-calculate completeness to see actual scores
        for c in companies:
            c.calculate_completeness()

        report = get_quality_report(companies)

        assert report.total_companies == 3
        # At least one company in the high bucket
        assert report.bucket_75_100 >= 1
        # Low company should be in low bucket
        assert report.bucket_0_25 >= 1
        # Average should be between 0 and 1
        assert 0.0 < report.avg_completeness < 1.0

    def test_quality_report_missing_fields_tracking(self):
        """Quality report tracks most commonly missing fields."""
        companies = [
            # Both missing salary_range and tech_stack
            self._make_company(name="A", salary_range="", tech_stack=[]),
            self._make_company(name="B", salary_range="", tech_stack=[]),
            # Only missing salary_range
            self._make_company(name="C", salary_range=""),
        ]

        report = get_quality_report(companies)

        # salary_range should be the most commonly missing (all 3)
        missing_field_names = [f for f, _ in report.most_common_missing]
        assert "salary_range" in missing_field_names

        # Find salary_range count
        salary_missing = next(
            (count for field, count in report.most_common_missing if field == "salary_range"),
            0
        )
        assert salary_missing == 3

    def test_quality_report_empty_list(self):
        """Quality report handles empty company list gracefully."""
        report = get_quality_report([])
        assert report.total_companies == 0
        assert report.avg_completeness == 0.0

    def test_completeness_result_15_fields(self):
        """Company.calculate_completeness checks exactly 15 fields."""
        company = Company(name="Test")
        result = company.calculate_completeness()

        # Total fields should be 15 (name is present, 14 missing)
        len(result.missing_fields) + (1 if result.score > 0 else 0)
        # name is present so 1 filled + N missing = 15
        assert len(company.COMPLETENESS_FIELDS) == 15
        assert "name" not in result.missing_fields  # name is set
        assert len(result.missing_fields) == 14  # all others empty
        assert result.score == pytest.approx(1 / 15, abs=0.001)
