"""End-to-end integration tests for the full outreach pipeline."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM, OutreachORM


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def _seed_tier1_company(session, name="TestCo", fit_score=90.0, contact_name="Jane Doe"):
    """Seed a Tier 1 company with contact for testing."""
    company = CompanyORM(
        name=name,
        tier="Tier 1 - HIGH",
        fit_score=fit_score,
        h1b_status="Confirmed",
        is_disqualified=False,
        stage="To apply",
        description=f"{name} is an AI startup headquartered in San Francisco, CA with 50 employees",
        funding_stage="Series A",
        data_completeness=60.0,
        website=f"https://{name.lower().replace(' ', '')}.com",
        differentiators="graph,rag",
        role="AI Engineer",
    )
    session.add(company)
    session.flush()

    contact = ContactORM(
        name=contact_name,
        title="CTO",
        company_id=company.id,
        company_name=name,
        linkedin_url=f"https://linkedin.com/in/{contact_name.lower().replace(' ', '')}",
        contact_score=8.0,
    )
    session.add(contact)
    session.flush()

    return company, contact


# --------------------------------------------------------------------------- #
# 1. Full flow: seed -> score -> draft -> sequence -> mark_sent -> followup
# --------------------------------------------------------------------------- #


@patch("src.outreach.template_engine.SequenceBuilder.build_sequence")
@patch("src.outreach.template_engine.OutreachTemplateEngine.render")
@patch("src.validators.scoring_engine.FitScoringEngine.__init__", return_value=None)
@patch("src.validators.scoring_engine.FitScoringEngine.score")
def test_full_flow_seed_to_followup(mock_score, mock_init, mock_render, mock_seq, session):
    """Create company + contact -> score -> draft -> sequence -> mark_sent -> detect overdue."""
    # Setup mocks
    mock_breakdown = MagicMock()
    mock_breakdown.total = 85.0
    mock_breakdown.h1b_score = 15.0
    mock_breakdown.criteria_score = 12.0
    mock_breakdown.tech_overlap_score = 8.0
    mock_breakdown.salary_score = 5.0
    mock_breakdown.profile_jd_similarity = 20.0
    mock_breakdown.domain_company_similarity = 15.0
    mock_breakdown.domain_match_bonus = 10.0
    mock_score.return_value = mock_breakdown

    mock_render.return_value = ("Hi there, this is a test message for outreach.", True, 46)
    mock_seq.return_value = [
        {"step": "pre_engagement", "date": "2026-03-06", "day": "Friday"},
        {"step": "connection_request", "date": "2026-03-07", "day": "Saturday"},
    ]

    company, contact = _seed_tier1_company(session, name="FlowCo")

    # Step 1: Score
    from src.pipeline.orchestrator import Pipeline

    pipeline = Pipeline(session)
    result = pipeline.score_all(include_semantic=False)
    assert result["scored"] >= 1

    # Step 2: Draft outreach
    from src.outreach.batch_engine import BatchOutreachEngine

    engine = BatchOutreachEngine(session)
    drafts = engine.draft_for_company(company, contact, template_types=["connection_request"])
    assert len(drafts) >= 1
    assert drafts[0].stage == "Not Started"

    # Step 3: Mark sent
    from src.outreach.sequence_tracker import SequenceTracker

    tracker = SequenceTracker(session)
    sent = tracker.mark_sent("FlowCo", "connection_request", contact_name="Jane Doe")
    assert sent is not None
    assert sent.stage == "Sent"

    # Step 4: Backdate sent_at so follow-up becomes overdue
    sent.sent_at = datetime.now() - timedelta(days=15)
    session.commit()

    # Step 5: Detect overdue
    from src.outreach.followup_manager import FollowUpManager

    fm = FollowUpManager(session)
    overdue = fm.get_overdue_followups(grace_days=2)
    assert len(overdue) >= 1
    assert overdue[0]["company_name"] == "FlowCo"
    assert overdue[0]["days_overdue"] > 0


# --------------------------------------------------------------------------- #
# 2. Rate limit enforcement
# --------------------------------------------------------------------------- #


def test_rate_limit_enforcement(session):
    """Create 100 Sent OutreachORM records this week -> generate_daily_queue() returns empty."""
    company, _ = _seed_tier1_company(session, name="RateLimitCo")

    # Create 100 sent records this week (all within current week window)
    now = datetime.now()
    # Ensure all records fall after Monday 00:00 of this week
    monday = now - timedelta(days=now.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(100):
        # Spread records evenly within the current week
        offset_minutes = i * 5  # 5 min apart, all within a few hours
        record = OutreachORM(
            company_id=company.id,
            company_name="RateLimitCo",
            contact_name="Jane Doe",
            stage="Sent",
            sent_at=week_start + timedelta(minutes=offset_minutes + 1),
            sequence_step="connection_request",
            content=f"Message {i}",
        )
        session.add(record)
    session.flush()

    from src.outreach.send_queue import SendQueueManager

    manager = SendQueueManager(session)
    status = manager.get_rate_limit_status()
    assert status["sent_this_week"] == 100
    assert status["remaining"] == 0

    queue = manager.generate_daily_queue()
    assert queue == []


# --------------------------------------------------------------------------- #
# 3. Tier 1 kickoff end-to-end
# --------------------------------------------------------------------------- #


@patch("src.outreach.template_engine.SequenceBuilder.build_sequence")
@patch("src.outreach.template_engine.OutreachTemplateEngine.render")
def test_tier1_kickoff_end_to_end(mock_render, mock_seq, session):
    """Tier1Kickoff.run() creates drafts + sequences + report."""
    mock_render.return_value = ("Hi there, this is a test outreach message.", True, 43)
    mock_seq.return_value = [
        {"step": "pre_engagement", "date": "2026-03-06", "day": "Friday"},
        {"step": "connection_request", "date": "2026-03-07", "day": "Saturday"},
    ]

    _seed_tier1_company(session, name="KickoffAlpha", contact_name="Alice CTO")
    _seed_tier1_company(session, name="KickoffBeta", contact_name="Bob VP")

    from src.outreach.kickoff import Tier1Kickoff

    kickoff = Tier1Kickoff(session)
    ready = kickoff.get_ready_companies()
    assert len(ready) == 2

    result = kickoff.run(dry_run=False)
    assert result["drafted"] >= 2
    assert result["sequences_built"] >= 2
    assert "KickoffAlpha" in result["companies"]
    assert "KickoffBeta" in result["companies"]
    assert "Tier 1 Kickoff Report" in result["report"]


# --------------------------------------------------------------------------- #
# 4. Priority matrix after scoring
# --------------------------------------------------------------------------- #


@patch("src.validators.scoring_engine.FitScoringEngine.__init__", return_value=None)
@patch("src.validators.scoring_engine.FitScoringEngine.score")
def test_priority_matrix_after_scoring(mock_score, mock_init, session):
    """Pipeline.score_all() -> PriorityReporter.generate_priority_matrix() -> verify tier grouping."""
    mock_breakdown = MagicMock()
    mock_breakdown.total = 85.0
    mock_breakdown.h1b_score = 15.0
    mock_breakdown.criteria_score = 12.0
    mock_breakdown.tech_overlap_score = 8.0
    mock_breakdown.salary_score = 5.0
    mock_breakdown.profile_jd_similarity = 20.0
    mock_breakdown.domain_company_similarity = 15.0
    mock_breakdown.domain_match_bonus = 10.0
    mock_score.return_value = mock_breakdown

    _seed_tier1_company(session, name="PriorityCo", fit_score=90.0)

    # Add a Tier 2 company
    tier2 = CompanyORM(
        name="MidCo",
        tier="Tier 2 - STRONG",
        fit_score=70.0,
        h1b_status="Likely",
        is_disqualified=False,
        stage="To apply",
        description="MidCo is a mid-tier AI company",
    )
    session.add(tier2)
    session.flush()

    from src.pipeline.orchestrator import Pipeline

    pipeline = Pipeline(session)
    score_result = pipeline.score_all(include_semantic=False)
    assert score_result["scored"] >= 2

    from src.validators.priority_report import PriorityReporter

    reporter = PriorityReporter(session)
    matrix = reporter.generate_priority_matrix(include_semantic=False)

    assert "tiers" in matrix
    assert matrix["total_scored"] >= 2
    # Check tier grouping exists
    assert any("Tier 1" in t for t in matrix["tiers"])
    assert any("Tier 2" in t for t in matrix["tiers"])


# --------------------------------------------------------------------------- #
# 5. Enrichment then scoring
# --------------------------------------------------------------------------- #


def test_enrichment_then_scoring(session):
    """Create company with description containing 'Series B' and 'team of 100' -> enrich -> verify fields."""
    company = CompanyORM(
        name="EnrichCo",
        tier="Tier 2 - STRONG",
        h1b_status="Confirmed",
        is_disqualified=False,
        stage="To apply",
        description="EnrichCo is an AI startup headquartered in San Francisco, CA with a team of 100 employees. They raised a Series B.",
        funding_stage="Unknown",
        data_completeness=30.0,
    )
    session.add(company)
    session.flush()

    from src.pipeline.enrichment import CompanyEnricher

    enricher = CompanyEnricher(session)
    changes = enricher.enrich_from_description(company)

    assert "employees" in changes
    assert changes["employees"] == 100
    assert "funding_stage" in changes
    assert changes["funding_stage"] == "Series B"
    assert "hq_location" in changes
    assert "San Francisco" in changes["hq_location"]


# --------------------------------------------------------------------------- #
# 6. Sequence tracker full cycle
# --------------------------------------------------------------------------- #


def test_sequence_tracker_full_cycle(session):
    """mark_sent(step1) -> mark_sent(step2) -> get_status -> mark_responded."""
    company, contact = _seed_tier1_company(session, name="SeqCo")

    from src.outreach.sequence_tracker import SequenceTracker

    tracker = SequenceTracker(session)

    # Step 1: Mark connection_request sent
    r1 = tracker.mark_sent("SeqCo", "connection_request", contact_name="Jane Doe")
    assert r1 is not None
    assert r1.stage == "Sent"

    # Step 2: Mark follow_up sent
    r2 = tracker.mark_sent("SeqCo", "follow_up", contact_name="Jane Doe")
    assert r2 is not None
    assert r2.stage == "Sent"

    # Step 3: Get sequence status
    status = tracker.get_sequence_status("SeqCo")
    assert status["company"] == "SeqCo"
    assert "connection_request" in status["steps_completed"]
    assert "follow_up" in status["steps_completed"]
    assert status["total_sent"] == 2
    assert status["has_response"] is False

    # Step 4: Mark responded
    responded = tracker.mark_responded("SeqCo", response_text="Thanks for reaching out!")
    assert responded is not None
    assert responded.stage == "Responded"
    assert responded.response_text == "Thanks for reaching out!"

    # Verify status updated
    status2 = tracker.get_sequence_status("SeqCo")
    assert status2["has_response"] is True


# --------------------------------------------------------------------------- #
# 7. Followup detection timing
# --------------------------------------------------------------------------- #


def test_followup_detection_timing(session):
    """Create Sent record 10 days old -> FollowUpManager detects as overdue."""
    company, _ = _seed_tier1_company(session, name="OverdueCo")

    # Create a Sent record with sent_at 10 days ago
    record = OutreachORM(
        company_id=company.id,
        company_name="OverdueCo",
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=10),
        sequence_step="connection_request",
        content="Hello!",
    )
    session.add(record)
    session.commit()

    from src.outreach.followup_manager import FollowUpManager

    fm = FollowUpManager(session)
    overdue = fm.get_overdue_followups(grace_days=2)

    assert len(overdue) >= 1
    found = [o for o in overdue if o["company_name"] == "OverdueCo"]
    assert len(found) == 1
    assert found[0]["last_step"] == "connection_request"
    assert found[0]["next_step"] == "follow_up"
    assert found[0]["days_overdue"] > 0
    # Gap is 3 days + 2 grace = 5 days, sent 10 days ago, so ~5 days overdue
    assert found[0]["days_overdue"] >= 4


# --------------------------------------------------------------------------- #
# 8. Domain breakdown integration
# --------------------------------------------------------------------------- #


def test_domain_breakdown_integration(session):
    """Create varied companies -> DomainMatchScorer.batch_score -> verify grouping."""
    # Graph RAG company
    c1 = CompanyORM(
        name="GraphAI",
        description="Building knowledge graph and retrieval augmented generation systems with Neo4j and vector embeddings",
        is_disqualified=False,
        differentiators="graph,rag,semantic search",
    )
    # Healthcare company
    c2 = CompanyORM(
        name="HealthTech",
        description="AI for clinical patient care and medical diagnostics in healthcare",
        is_disqualified=False,
        differentiators="health,clinical",
    )
    # Generic ML infra
    c3 = CompanyORM(
        name="InfraCo",
        description="ML infrastructure and model serving deployment pipeline platform",
        is_disqualified=False,
        differentiators="mlops,infrastructure",
    )
    session.add_all([c1, c2, c3])
    session.flush()

    from src.validators.domain_scorer import DomainMatchScorer

    scorer = DomainMatchScorer()
    results = scorer.batch_score([c1, c2, c3])

    assert len(results) == 3
    # Each result is (company, score, domain)
    domains_found = {r[2] for r in results}
    # At least two different domains should be matched
    assert len(domains_found) >= 2

    # Results should be sorted by score descending
    scores = [r[1] for r in results]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- #
# 9. Send queue priority ordering
# --------------------------------------------------------------------------- #


@patch("src.outreach.template_engine.OutreachTemplateEngine.render")
def test_send_queue_priority_ordering(mock_render, session):
    """Create 5 companies with different fit_scores -> queue returns highest first."""
    mock_render.return_value = ("Test outreach message for priority ordering.", True, 46)

    scores = [60.0, 95.0, 70.0, 85.0, 50.0]
    for i, score in enumerate(scores):
        company = CompanyORM(
            name=f"QueueCo_{i}",
            tier="Tier 1 - HIGH",
            fit_score=score,
            h1b_status="Confirmed",
            is_disqualified=False,
            stage="To apply",
            description=f"AI company {i}",
            differentiators="ai",
            role="AI Engineer",
        )
        session.add(company)
        session.flush()

        contact = ContactORM(
            name=f"Contact_{i}",
            title="CTO",
            company_id=company.id,
            company_name=f"QueueCo_{i}",
            contact_score=7.0,
        )
        session.add(contact)
        session.flush()

        # Create a Not Started outreach record
        from src.outreach.batch_engine import BatchOutreachEngine

        engine = BatchOutreachEngine(session)
        engine.draft_for_company(company, contact, template_types=["connection_request"])

    session.commit()

    from src.outreach.send_queue import SendQueueManager

    manager = SendQueueManager(session)
    queue = manager.generate_daily_queue(max_sends=5)

    assert len(queue) == 5
    # First item should be highest fit_score (95.0)
    assert queue[0]["fit_score"] == 95.0
    # Last should be lowest (50.0)
    assert queue[-1]["fit_score"] == 50.0
    # All should be in descending order
    fit_scores = [item["fit_score"] for item in queue]
    assert fit_scores == sorted(fit_scores, reverse=True)


# --------------------------------------------------------------------------- #
# 10. Data completeness recalculation
# --------------------------------------------------------------------------- #


def test_data_completeness_recalculation(session):
    """Create partially filled companies -> compute_all_completeness -> verify percentages."""
    # Well-filled company
    c1 = CompanyORM(
        name="FullCo",
        description="AI startup doing amazing things",
        hq_location="San Francisco, CA",
        employees=50,
        funding_stage="Series A",
        h1b_status="Confirmed",
        role="AI Engineer",
        hiring_manager="John Smith",
        salary_range="$150k-$200k",
        website="https://fullco.com",
        is_disqualified=False,
        data_completeness=0.0,
    )
    # Sparse company
    c2 = CompanyORM(
        name="SparseCo",
        description="",
        hq_location="",
        employees=None,
        funding_stage="Unknown",
        h1b_status="Unknown",
        role="",
        hiring_manager="",
        salary_range="",
        website="",
        is_disqualified=False,
        data_completeness=0.0,
    )
    session.add_all([c1, c2])
    session.commit()

    from src.pipeline.enrichment import CompanyEnricher

    enricher = CompanyEnricher(session)
    result = enricher.compute_all_completeness()

    assert result["updated"] == 2
    # FullCo should have high completeness (all 9 fields filled)
    session.refresh(c1)
    session.refresh(c2)
    assert c1.data_completeness > 80.0
    # SparseCo should have low completeness
    assert c2.data_completeness < 30.0


# --------------------------------------------------------------------------- #
# 11. Outreach sync stage mapping
# --------------------------------------------------------------------------- #


def test_outreach_sync_stage_mapping(session):
    """Create Sent + Responded outreach -> OutreachNotionSync maps stages correctly."""
    company, _ = _seed_tier1_company(session, name="SyncCo")

    # Create Sent record
    sent_record = OutreachORM(
        company_id=company.id,
        company_name="SyncCo",
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=5),
        sequence_step="connection_request",
        content="Hello!",
    )
    session.add(sent_record)

    # Create another company with Responded
    company2, _ = _seed_tier1_company(session, name="RespCo", contact_name="Bob Smith")
    resp_record = OutreachORM(
        company_id=company2.id,
        company_name="RespCo",
        contact_name="Bob Smith",
        stage="Responded",
        sent_at=datetime.now() - timedelta(days=3),
        response_at=datetime.now(),
        sequence_step="connection_request",
        content="Hey!",
        response_text="Thanks for reaching out!",
    )
    session.add(resp_record)
    session.commit()

    from src.integrations.outreach_sync import OutreachNotionSync

    sync = OutreachNotionSync(
        api_key="fake-key",
        applications_db_id="fake-db-id",
        session=session,
    )

    # Test internal stage mapping methods (no actual Notion calls)
    grouped = sync._get_outreach_by_company()
    assert "SyncCo" in grouped
    assert "RespCo" in grouped

    # SyncCo has Sent, so best stage = Sent
    assert sync._get_best_stage(grouped["SyncCo"]) == "Sent"
    # RespCo has Responded, so best stage = Responded
    assert sync._get_best_stage(grouped["RespCo"]) == "Responded"

    # Test sync report generation
    report = sync.generate_sync_report()
    assert report["total_companies"] == 2
    assert "Sent" in report["stage_counts"]
    assert "Responded" in report["stage_counts"]


# --------------------------------------------------------------------------- #
# 12. Daily alert structure
# --------------------------------------------------------------------------- #


def test_daily_alert_structure(session):
    """Create mix of overdue/due records -> generate_daily_alert() -> verify dict keys + overdue count."""
    company1, _ = _seed_tier1_company(session, name="AlertCo1")
    company2, _ = _seed_tier1_company(session, name="AlertCo2", contact_name="Bob Smith")

    # AlertCo1: Sent 10 days ago (overdue)
    overdue_record = OutreachORM(
        company_id=company1.id,
        company_name="AlertCo1",
        contact_name="Jane Doe",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=10),
        sequence_step="connection_request",
        content="Hello!",
    )
    session.add(overdue_record)

    # AlertCo2: Sent 1 day ago (not yet overdue)
    recent_record = OutreachORM(
        company_id=company2.id,
        company_name="AlertCo2",
        contact_name="Bob Smith",
        stage="Sent",
        sent_at=datetime.now() - timedelta(days=1),
        sequence_step="connection_request",
        content="Hi!",
    )
    session.add(recent_record)
    session.commit()

    from src.outreach.followup_manager import FollowUpManager

    fm = FollowUpManager(session)
    alert = fm.generate_daily_alert()

    # Verify structure
    assert "overdue" in alert
    assert "due_today" in alert
    assert "due_this_week" in alert
    assert "total_active_sequences" in alert

    # AlertCo1 should be overdue
    assert len(alert["overdue"]) >= 1
    overdue_companies = [o["company_name"] for o in alert["overdue"]]
    assert "AlertCo1" in overdue_companies

    # Both are active sequences
    assert alert["total_active_sequences"] >= 2
