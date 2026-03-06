"""Tests for the ContactORM email column fix and EmailOutreach integration."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.db.orm import Base, CompanyORM, ContactORM, OutreachORM
from src.integrations.email_outreach import EmailOutreach


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def seeded_session(db_session):
    """Session pre-populated with a company, contact, and stale outreach record."""
    company = CompanyORM(
        name="TestCorp",
        description="AI testing company",
        tier="Tier 1",
        h1b_status="Confirmed",
        role="AI Engineer",
        ai_product_description="automated testing with AI",
    )
    db_session.add(company)
    db_session.flush()

    contact = ContactORM(
        name="Jane Doe",
        title="VP Engineering",
        company_id=company.id,
        company_name="TestCorp",
        linkedin_url="https://linkedin.com/in/janedoe",
        email="jane@testcorp.com",
    )
    db_session.add(contact)

    # Create a stale outreach record (sent 20 days ago, no response)
    outreach = OutreachORM(
        company_id=company.id,
        company_name="TestCorp",
        contact_name="Jane Doe",
        stage="Sent",
        sequence_step="connection_request",
        sent_at=datetime.now() - timedelta(days=20),
    )
    db_session.add(outreach)
    db_session.commit()

    return db_session


class TestContactORMEmailColumn:
    """Verify the email column exists on ContactORM."""

    def test_contact_orm_has_email_column(self, db_session):
        """ContactORM table should have an 'email' column."""
        inspector = inspect(db_session.bind)
        columns = [col["name"] for col in inspector.get_columns("contacts")]
        assert "email" in columns, f"'email' not found in contacts columns: {columns}"

    def test_contact_email_default_empty_string(self, db_session):
        """A new contact with no email should default to empty string."""
        contact = ContactORM(name="No Email Person", company_name="SomeCo")
        db_session.add(contact)
        db_session.commit()

        loaded = db_session.query(ContactORM).filter_by(name="No Email Person").first()
        assert loaded.email == ""

    def test_contact_email_stores_value(self, db_session):
        """A contact with an email should persist and return it."""
        contact = ContactORM(
            name="Has Email",
            company_name="SomeCo",
            email="has@email.com",
        )
        db_session.add(contact)
        db_session.commit()

        loaded = db_session.query(ContactORM).filter_by(name="Has Email").first()
        assert loaded.email == "has@email.com"


class TestStaleConnectionsEmailLookup:
    """Verify find_stale_connections returns real email from ContactORM."""

    def test_stale_connection_returns_email(self, seeded_session):
        """Stale connection for a contact with email should populate contact_email."""
        eo = EmailOutreach(seeded_session)
        stale = eo.find_stale_connections(threshold_days=14)

        assert len(stale) == 1
        assert stale[0]["contact_email"] == "jane@testcorp.com"

    def test_stale_connection_returns_none_when_no_email(self, seeded_session):
        """Stale connection for a contact without email returns None."""
        # Add a second contact with no email and a stale outreach for them
        company = seeded_session.query(CompanyORM).filter_by(name="TestCorp").first()

        contact_no_email = ContactORM(
            name="No Email",
            title="Recruiter",
            company_id=company.id,
            company_name="TestCorp",
            email="",
        )
        seeded_session.add(contact_no_email)

        outreach2 = OutreachORM(
            company_id=company.id,
            company_name="TestCorp",
            contact_name="No Email",
            stage="Sent",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=20),
        )
        seeded_session.add(outreach2)
        seeded_session.commit()

        eo = EmailOutreach(seeded_session)
        stale = eo.find_stale_connections(threshold_days=14)

        # Find the entry for "No Email"
        no_email_entry = [s for s in stale if s["contact_name"] == "No Email"]
        assert len(no_email_entry) == 1
        assert no_email_entry[0]["contact_email"] is None


class TestEmailDraftTo:
    """Verify generate_email_draft populates the 'to' field."""

    def test_draft_to_populated_when_contact_has_email(self, seeded_session):
        """Email draft 'to' field should be the contact's email when available."""
        eo = EmailOutreach(seeded_session)
        draft = eo.generate_email_draft("TestCorp", "Jane Doe")

        assert draft["to"] == "jane@testcorp.com"

    def test_draft_to_none_when_contact_has_no_email(self, seeded_session):
        """Email draft 'to' field should be None when contact has no email."""
        # Add contact with empty email
        company = seeded_session.query(CompanyORM).filter_by(name="TestCorp").first()
        contact = ContactORM(
            name="Empty Email",
            title="CTO",
            company_id=company.id,
            company_name="TestCorp",
            email="",
        )
        seeded_session.add(contact)
        seeded_session.commit()

        eo = EmailOutreach(seeded_session)
        draft = eo.generate_email_draft("TestCorp", "Empty Email")

        assert draft["to"] is None

    def test_draft_to_none_when_contact_not_found(self, seeded_session):
        """Email draft 'to' field should be None when contact doesn't exist."""
        eo = EmailOutreach(seeded_session)
        draft = eo.generate_email_draft("TestCorp", "Nonexistent Person")

        assert draft["to"] is None


class TestBatchPrepareEmailCounts:
    """Verify batch_prepare_emails correctly counts with_email vs without_email."""

    def test_batch_counts_with_mixed_emails(self, seeded_session):
        """Batch prepare should correctly count contacts with and without email."""
        # seeded_session has 1 stale with email (Jane Doe @ TestCorp)
        # Add another stale without email
        company = seeded_session.query(CompanyORM).filter_by(name="TestCorp").first()

        contact = ContactORM(
            name="No Email Contact",
            title="Recruiter",
            company_id=company.id,
            company_name="TestCorp",
            email="",
        )
        seeded_session.add(contact)

        outreach = OutreachORM(
            company_id=company.id,
            company_name="TestCorp",
            contact_name="No Email Contact",
            stage="Sent",
            sequence_step="connection_request",
            sent_at=datetime.now() - timedelta(days=20),
        )
        seeded_session.add(outreach)
        seeded_session.commit()

        eo = EmailOutreach(seeded_session)
        result = eo.batch_prepare_emails(threshold_days=14)

        assert result["total_stale"] == 2
        # 1 has email (Jane Doe), 1 does not (No Email Contact)
        assert result["skipped_no_email"] == 1
        assert len(result["drafts"]) == 2
