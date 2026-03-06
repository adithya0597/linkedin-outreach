"""Tests for EmailOutreach — stale connection detection and email draft generation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM, OutreachORM
from src.integrations.email_outreach import STALE_THRESHOLD_DAYS, EmailOutreach


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


@pytest.fixture()
def populated_session(session):
    """Session with company, contact, and a stale outreach record."""
    company = CompanyORM(
        name="Acme AI",
        role="AI Engineer",
        ai_product_description="autonomous agents for enterprise workflows",
    )
    session.add(company)
    session.flush()

    contact = ContactORM(
        name="Jane Doe",
        title="VP Engineering",
        company_id=company.id,
        company_name="Acme AI",
        linkedin_url="https://linkedin.com/in/janedoe",
    )
    session.add(contact)

    # Stale outreach: sent 20 days ago, no response
    outreach = OutreachORM(
        company_name="Acme AI",
        contact_name="Jane Doe",
        stage="Sent",
        sequence_step="connection_request",
        sent_at=datetime.now() - timedelta(days=20),
        company_id=company.id,
    )
    session.add(outreach)
    session.commit()
    return session


class TestFindStaleConnections:
    def test_finds_stale_connections(self, populated_session):
        eo = EmailOutreach(populated_session)
        stale = eo.find_stale_connections()

        assert len(stale) == 1
        assert stale[0]["company_name"] == "Acme AI"
        assert stale[0]["contact_name"] == "Jane Doe"
        assert stale[0]["days_since_sent"] >= 20
        assert stale[0]["contact_email"] is None

    def test_excludes_fresh_connections(self, session):
        """Connections sent within threshold should not appear."""
        company = CompanyORM(name="Fresh Co", role="ML Engineer")
        session.add(company)
        session.flush()

        outreach = OutreachORM(
            company_name="Fresh Co",
            contact_name="Bob Smith",
            stage="Sent",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=5),
            company_id=company.id,
        )
        session.add(outreach)
        session.commit()

        eo = EmailOutreach(session)
        stale = eo.find_stale_connections()
        assert len(stale) == 0

    def test_excludes_responded_connections(self, session):
        """Connections that got a response should not appear, even if old."""
        company = CompanyORM(name="Responded Co", role="Engineer")
        session.add(company)
        session.flush()

        # Old sent record
        sent = OutreachORM(
            company_name="Responded Co",
            contact_name="Alice",
            stage="Sent",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=30),
            company_id=company.id,
        )
        # Responded record for same company
        responded = OutreachORM(
            company_name="Responded Co",
            contact_name="Alice",
            stage="Responded",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=30),
            response_at=datetime.now() - timedelta(days=25),
            company_id=company.id,
        )
        session.add_all([sent, responded])
        session.commit()

        eo = EmailOutreach(session)
        stale = eo.find_stale_connections()
        assert len(stale) == 0

    def test_empty_results_when_no_stale(self, session):
        """No outreach records means no stale connections."""
        eo = EmailOutreach(session)
        stale = eo.find_stale_connections()
        assert stale == []

    def test_threshold_days_parameter(self, session):
        """Custom threshold_days should be respected."""
        company = CompanyORM(name="Threshold Co", role="Engineer")
        session.add(company)
        session.flush()

        outreach = OutreachORM(
            company_name="Threshold Co",
            contact_name="Charlie",
            stage="Sent",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=10),
            company_id=company.id,
        )
        session.add(outreach)
        session.commit()

        eo = EmailOutreach(session)

        # Default threshold (14 days) — should NOT find it
        assert len(eo.find_stale_connections()) == 0

        # Custom threshold (7 days) — SHOULD find it
        assert len(eo.find_stale_connections(threshold_days=7)) == 1


class TestGenerateEmailDraft:
    def test_draft_subject_format(self, populated_session):
        eo = EmailOutreach(populated_session)
        draft = eo.generate_email_draft("Acme AI", "Jane Doe")

        assert draft["subject"] == "Re: AI Engineer opportunity at Acme AI"

    def test_draft_body_includes_company_context(self, populated_session):
        eo = EmailOutreach(populated_session)
        draft = eo.generate_email_draft("Acme AI", "Jane Doe")

        assert "Acme AI" in draft["body"]
        assert "autonomous agents" in draft["body"]
        assert "Jane" in draft["body"]

    def test_draft_structure(self, populated_session):
        eo = EmailOutreach(populated_session)
        draft = eo.generate_email_draft("Acme AI", "Jane Doe")

        assert draft["to"] is None
        assert draft["company"] == "Acme AI"
        assert draft["contact"] == "Jane Doe"
        assert isinstance(draft["body"], str)
        assert len(draft["body"]) > 0


class TestBatchPrepareEmails:
    def test_batch_handles_missing_emails(self, populated_session):
        """All contacts lack email — skipped_no_email should equal total_stale."""
        eo = EmailOutreach(populated_session)
        result = eo.batch_prepare_emails()

        assert result["total_stale"] == 1
        assert result["skipped_no_email"] == 1
        assert len(result["drafts"]) == 1


class TestGetEmailStatus:
    def test_status_counts(self, populated_session):
        eo = EmailOutreach(populated_session)
        # Prepare some drafts first
        eo.batch_prepare_emails()
        status = eo.get_email_status()

        assert status["total_stale"] == 1
        assert status["with_email"] == 0
        assert status["without_email"] == 1
        assert status["drafts_prepared"] == 1
