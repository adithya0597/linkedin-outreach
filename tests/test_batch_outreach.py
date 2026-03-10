"""Tests for batch outreach engine — drafting, template rotation, sequence building, ORM persistence."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM, OutreachORM
from src.outreach.batch_engine import BatchOutreachEngine
from src.outreach.personalizer import OutreachPersonalizer


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def sample_company(db_session):
    """Tier 1 AI company with fit score."""
    company = CompanyORM(
        name="TestCorp",
        description="AI startup building graph RAG",
        tier="Tier 1 - HIGH",
        h1b_status="Confirmed",
        role="AI Engineer",
        fit_score=90.0,
        is_disqualified=False,
        differentiators="graph,rag",
    )
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def sample_contact(db_session, sample_company):
    """CTO contact linked to sample company."""
    contact = ContactORM(
        name="Jane Doe",
        title="CTO",
        company_id=sample_company.id,
        company_name="TestCorp",
        contact_score=9.0,
    )
    db_session.add(contact)
    db_session.flush()
    return contact


@pytest.fixture
def recruiter_contact(db_session, sample_company):
    """Recruiter contact linked to sample company."""
    contact = ContactORM(
        name="Bob Recruiter",
        title="Senior Recruiter",
        company_id=sample_company.id,
        company_name="TestCorp",
        contact_score=7.0,
    )
    db_session.add(contact)
    db_session.flush()
    return contact


@pytest.fixture
def disqualified_company(db_session):
    """Company that is disqualified."""
    company = CompanyORM(
        name="BadCorp",
        description="Consulting firm",
        tier="Tier 1 - HIGH",
        is_disqualified=True,
        disqualification_reason="Staffing firm",
        differentiators="",
    )
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def tier2_company(db_session):
    """Tier 2 company for filtering tests."""
    company = CompanyORM(
        name="MidCorp",
        description="ML infrastructure platform",
        tier="Tier 2 - STRONG",
        h1b_status="Likely",
        role="ML Engineer",
        fit_score=80.0,
        is_disqualified=False,
        differentiators="infrastructure,mlops",
    )
    db_session.add(company)
    db_session.flush()
    return company


def _mock_render(template_name, context, message_type="follow_up"):
    """Mock render that returns short text with template name embedded."""
    text = f"Hi, this is a {message_type} from template {template_name}."
    char_count = len(text)
    is_valid = char_count <= 300 if "connection" in message_type else True
    return text, is_valid, char_count


class TestBatchOutreachEngine:
    def test_draft_creates_orm_record(self, db_session, sample_company, sample_contact):
        """Drafting a company creates an OutreachORM record in the database."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            drafts = engine.draft_for_company(sample_company, sample_contact)

        assert len(drafts) == 1
        record = drafts[0]
        assert record.company_id == sample_company.id
        assert record.company_name == "TestCorp"
        assert record.contact_name == "Jane Doe"
        assert record.stage == "Not Started"
        # Verify it's in the database
        count = db_session.query(OutreachORM).filter(
            OutreachORM.company_id == sample_company.id
        ).count()
        assert count == 1

    def test_draft_filters_by_tier(self, db_session, sample_company, tier2_company):
        """draft_all with tier filter only drafts matching companies."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            results = engine.draft_all(tier="Tier 1 - HIGH")

        assert results["drafted"] == 1
        # Tier 2 should not be drafted
        tier2_drafts = db_session.query(OutreachORM).filter(
            OutreachORM.company_id == tier2_company.id
        ).count()
        assert tier2_drafts == 0

    def test_draft_skips_disqualified(self, db_session, sample_company, disqualified_company):
        """Disqualified companies are excluded from batch drafting."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            results = engine.draft_all()

        # Only sample_company should be drafted, not disqualified_company
        disq_drafts = db_session.query(OutreachORM).filter(
            OutreachORM.company_id == disqualified_company.id
        ).count()
        assert disq_drafts == 0
        assert results["drafted"] >= 1

    def test_template_rotation(self, db_session, sample_company, sample_contact):
        """Calling draft_for_company twice uses different templates."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            drafts1 = engine.draft_for_company(sample_company, sample_contact)
            drafts2 = engine.draft_for_company(sample_company, sample_contact)

        template1 = drafts1[0].template_type
        template2 = drafts2[0].template_type
        # Second call should rotate to a different template
        assert template1 != template2

    def test_char_limit_validation(self, db_session, sample_company, sample_contact):
        """Connection requests are validated against 300 char limit."""
        def _render_long(template_name, context, message_type="follow_up"):
            text = "x" * 350
            is_valid = len(text) <= 300 if "connection" in message_type else True
            return text, is_valid, len(text)

        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_render_long):
            drafts = engine.draft_for_company(
                sample_company, sample_contact, ["connection_request"]
            )

        assert len(drafts) == 1
        assert drafts[0].is_within_limit is False
        assert drafts[0].character_count == 350
        assert drafts[0].char_limit == 300

    def test_draft_all_returns_counts(self, db_session, sample_company, tier2_company):
        """draft_all returns dict with drafted/skipped/over_limit/errors keys."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            results = engine.draft_all()

        assert "drafted" in results
        assert "skipped" in results
        assert "over_limit" in results
        assert "errors" in results
        assert isinstance(results["errors"], list)
        assert results["drafted"] >= 1

    def test_draft_all_with_limit(self, db_session, sample_company, tier2_company):
        """draft_all respects limit parameter."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            engine.draft_all(limit=1)

        total = db_session.query(OutreachORM).count()
        assert total == 1

    def test_contact_role_template_selection_cto(self, db_session, sample_company, sample_contact):
        """CTO contact gets technical template (connection_request_a.j2)."""
        engine = BatchOutreachEngine(db_session)
        template = engine._select_template("connection_request", sample_contact, [])
        assert template == "connection_request_a.j2"

    def test_contact_role_template_selection_recruiter(self, db_session, sample_company, recruiter_contact):
        """Recruiter contact gets metrics template (connection_request_b.j2)."""
        engine = BatchOutreachEngine(db_session)
        template = engine._select_template("connection_request", recruiter_contact, [])
        assert template == "connection_request_b.j2"

    def test_no_contact_uses_balanced(self, db_session, sample_company):
        """Company with no contact uses balanced template for connection requests."""
        engine = BatchOutreachEngine(db_session)
        # No contact, no existing templates — should pick role-based but since no contact,
        # the _select_template falls through to pool rotation (first in pool)
        template = engine._select_template("connection_request", None, [])
        assert template == "connection_request_a.j2"

    def test_draft_all_error_handling(self, db_session, sample_company):
        """Errors during drafting are captured, not raised."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=Exception("template error")):
            results = engine.draft_all()

        assert len(results["errors"]) == 1
        assert "TestCorp" in results["errors"][0]

    def test_multiple_template_types(self, db_session, sample_company, sample_contact):
        """Drafting multiple template types creates multiple records."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            drafts = engine.draft_for_company(
                sample_company, sample_contact,
                ["connection_request", "follow_up"]
            )

        assert len(drafts) == 2
        steps = {d.sequence_step for d in drafts}
        assert "connection_request" in steps
        assert "follow_up" in steps


class TestMultiTemplateVariants:
    def test_distinct_texts_per_template(self):
        """Each template produces different text via multi_template_variants."""
        personalizer = OutreachPersonalizer()
        templates = [
            "connection_request_a.j2",
            "connection_request_b.j2",
            "connection_request_c.j2",
        ]

        def _render_by_template(template_name, context, message_type="follow_up"):
            text = f"Rendered by {template_name}: {context.get('company', '')}"
            return text, True, len(text)

        with patch.object(personalizer.engine, "render", side_effect=_render_by_template):
            variants = personalizer.generate_multi_template_variants(
                templates, {"company": "TestCo"}, "connection_request"
            )

        texts = [v[0] for v in variants]
        assert len(set(texts)) == 3  # all distinct

    def test_template_name_in_tuple(self):
        """4th element of each variant tuple is the template name."""
        personalizer = OutreachPersonalizer()
        templates = ["connection_request_a.j2", "follow_up_a.j2"]

        mock_render = MagicMock(return_value=("text", True, 4))
        with patch.object(personalizer.engine, "render", mock_render):
            variants = personalizer.generate_multi_template_variants(
                templates, {}, "connection_request"
            )

        assert len(variants) == 2
        assert variants[0][3] == "connection_request_a.j2"
        assert variants[1][3] == "follow_up_a.j2"

    def test_char_limits_respected(self):
        """Variants report correct is_valid based on char limits."""
        personalizer = OutreachPersonalizer()

        def _render_varying(template_name, context, message_type="follow_up"):
            if "a.j2" in template_name:
                return "x" * 250, True, 250  # within limit
            return "x" * 350, False, 350  # over limit

        with patch.object(personalizer.engine, "render", side_effect=_render_varying):
            variants = personalizer.generate_multi_template_variants(
                ["connection_request_a.j2", "connection_request_b.j2"],
                {},
                "connection_request",
            )

        assert variants[0][1] is True   # a.j2 within limit
        assert variants[1][1] is False  # b.j2 over limit


class TestGetBestTemplateForContact:
    def test_cto_gets_technical(self):
        personalizer = OutreachPersonalizer()
        contact = ContactORM(name="Test", title="CTO")
        assert personalizer.get_best_template_for_contact(contact) == "connection_request_a.j2"

    def test_recruiter_gets_metrics(self):
        personalizer = OutreachPersonalizer()
        contact = ContactORM(name="Test", title="Senior Talent Acquisition")
        assert personalizer.get_best_template_for_contact(contact) == "connection_request_b.j2"

    def test_generic_gets_balanced(self):
        personalizer = OutreachPersonalizer()
        contact = ContactORM(name="Test", title="Software Engineer")
        assert personalizer.get_best_template_for_contact(contact) == "connection_request_c.j2"

    def test_follow_up_type(self):
        personalizer = OutreachPersonalizer()
        contact = ContactORM(name="Test", title="CTO")
        assert personalizer.get_best_template_for_contact(contact, "follow_up") == "follow_up_a.j2"

    def test_inmail_type(self):
        personalizer = OutreachPersonalizer()
        contact = ContactORM(name="Test", title="CTO")
        assert personalizer.get_best_template_for_contact(contact, "inmail") == "inmail_a.j2"


class TestSequenceIntegration:
    def test_five_step_sequence(self, db_session, sample_company, sample_contact):
        """build_sequence returns 5 steps."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            sequence = engine.build_sequence("TestCorp", "Jane Doe", "2026-03-10")

        assert len(sequence) == 5

    def test_tue_thu_dates(self, db_session, sample_company, sample_contact):
        """All sequence dates fall on Tuesday or Thursday."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            sequence = engine.build_sequence("TestCorp", "Jane Doe", "2026-03-10")

        for step in sequence:
            date = datetime.strptime(step["date"], "%Y-%m-%d")
            assert date.weekday() in (1, 3), (
                f"Step '{step['step']}' on {step['date']} ({step['day']}) is not Tue/Thu"
            )

    def test_template_recommendations(self, db_session, sample_company, sample_contact):
        """Each step has a template recommendation."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            sequence = engine.build_sequence("TestCorp", "Jane Doe", "2026-03-10")

        for step in sequence:
            assert "template" in step
            assert step["template"].endswith(".j2")

    def test_sequence_creates_orm_records(self, db_session, sample_company, sample_contact):
        """build_sequence creates 5 OutreachORM records."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            engine.build_sequence("TestCorp", "Jane Doe", "2026-03-10")

        count = db_session.query(OutreachORM).filter(
            OutreachORM.company_id == sample_company.id
        ).count()
        assert count == 5

    def test_sequence_company_not_found(self, db_session):
        """build_sequence returns empty list for unknown company."""
        engine = BatchOutreachEngine(db_session)
        sequence = engine.build_sequence("NonExistent", "Nobody", "2026-03-10")
        assert sequence == []

    def test_sequence_step_names(self, db_session, sample_company, sample_contact):
        """Sequence steps follow the expected order."""
        engine = BatchOutreachEngine(db_session)
        with patch.object(engine.engine, "render", side_effect=_mock_render):
            sequence = engine.build_sequence("TestCorp", "Jane Doe", "2026-03-10")

        step_names = [s["step"] for s in sequence]
        assert step_names == [
            "pre_engagement",
            "connection_request",
            "follow_up",
            "deeper_engagement",
            "final_touch",
        ]
