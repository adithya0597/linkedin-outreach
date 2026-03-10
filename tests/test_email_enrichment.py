"""Tests for email enrichment module with Hunter.io backend."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM, ContactORM
from src.integrations.email_enrichment import (
    EmailEnricher,
    EmailEnrichmentBackend,
    HunterIOBackend,
    ManualBackend,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_engine():
    """In-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mem_session(mem_engine):
    """Session bound to in-memory engine."""
    factory = sessionmaker(bind=mem_engine)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture
def seed_company(mem_session):
    """Insert a company with a website and return it."""
    company = CompanyORM(
        name="Acme AI",
        description="AI-native startup",
        hq_location="San Francisco, CA",
        employees=50,
        funding_stage="Series A",
        is_ai_native=True,
        h1b_status="Confirmed",
        website="https://www.acmeai.com/about",
    )
    mem_session.add(company)
    mem_session.commit()
    return company


@pytest.fixture
def seed_contact(mem_session, seed_company):
    """Insert a contact with empty email and return it."""
    contact = ContactORM(
        name="Jane Doe",
        title="CTO",
        company_id=seed_company.id,
        company_name="Acme AI",
        email="",
        contact_score=50.0,
    )
    mem_session.add(contact)
    mem_session.commit()
    return contact


class FakeBackend:
    """Test backend that returns a predictable email."""

    def __init__(self, email: str | None = "jane@acmeai.com"):
        self._email = email

    def find_email(self, first_name: str, last_name: str, domain: str) -> str | None:
        return self._email


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_hunter_backend_is_email_enrichment_backend(self):
        """HunterIOBackend satisfies the EmailEnrichmentBackend protocol."""
        backend = HunterIOBackend(api_key="test")
        assert isinstance(backend, EmailEnrichmentBackend)

    def test_manual_backend_is_email_enrichment_backend(self):
        """ManualBackend satisfies the EmailEnrichmentBackend protocol."""
        backend = ManualBackend()
        assert isinstance(backend, EmailEnrichmentBackend)


# ---------------------------------------------------------------------------
# ManualBackend
# ---------------------------------------------------------------------------

class TestManualBackend:
    def test_find_email_returns_none(self):
        """ManualBackend always returns None."""
        backend = ManualBackend()
        result = backend.find_email("Jane", "Doe", "acmeai.com")
        assert result is None


# ---------------------------------------------------------------------------
# EmailEnricher.enrich_contact
# ---------------------------------------------------------------------------

class TestEnrichContact:
    def test_enrich_contact_stores_email(self, mem_session, seed_company, seed_contact):
        """When backend finds email, it is stored on the ContactORM."""
        enricher = EmailEnricher(mem_session, backend=FakeBackend("jane@acmeai.com"))
        result = enricher.enrich_contact("Jane Doe", "Acme AI")

        assert result == "jane@acmeai.com"
        # Verify persisted
        contact = mem_session.query(ContactORM).filter(
            ContactORM.name == "Jane Doe"
        ).first()
        assert contact.email == "jane@acmeai.com"

    def test_enrich_contact_returns_none_when_not_found(self, mem_session, seed_company, seed_contact):
        """When backend returns None, enrich_contact returns None."""
        enricher = EmailEnricher(mem_session, backend=FakeBackend(None))
        result = enricher.enrich_contact("Jane Doe", "Acme AI")

        assert result is None
        # Email should remain empty
        contact = mem_session.query(ContactORM).filter(
            ContactORM.name == "Jane Doe"
        ).first()
        assert contact.email == ""

    def test_enrich_contact_single_name_returns_none(self, mem_session, seed_company):
        """Single-word name cannot be split into first/last — returns None."""
        enricher = EmailEnricher(mem_session, backend=FakeBackend("x@y.com"))
        result = enricher.enrich_contact("Madonna", "Acme AI")
        assert result is None


# ---------------------------------------------------------------------------
# EmailEnricher.batch_enrich
# ---------------------------------------------------------------------------

class TestBatchEnrich:
    def test_batch_enrich_enriches_contacts(self, mem_session, seed_company, seed_contact):
        """batch_enrich finds and stores emails for contacts with empty email."""
        enricher = EmailEnricher(mem_session, backend=FakeBackend("jane@acmeai.com"))
        result = enricher.batch_enrich(limit=10)

        assert result["enriched"] == 1
        assert result["failed"] == 0
        assert result["skipped"] == 0

        contact = mem_session.query(ContactORM).filter(
            ContactORM.name == "Jane Doe"
        ).first()
        assert contact.email == "jane@acmeai.com"

    def test_batch_enrich_skips_single_name(self, mem_session, seed_company):
        """Contacts with single-word names are skipped."""
        contact = ContactORM(
            name="Cher",
            title="CEO",
            company_id=seed_company.id,
            company_name="Acme AI",
            email="",
            contact_score=10.0,
        )
        mem_session.add(contact)
        mem_session.commit()

        enricher = EmailEnricher(mem_session, backend=FakeBackend("cher@acmeai.com"))
        result = enricher.batch_enrich(limit=10)
        assert result["skipped"] == 1
        assert result["enriched"] == 0

    def test_batch_enrich_counts_failures(self, mem_session, seed_company, seed_contact):
        """When backend returns None, counts as failed."""
        enricher = EmailEnricher(mem_session, backend=FakeBackend(None))
        result = enricher.batch_enrich(limit=10)
        assert result["failed"] == 1
        assert result["enriched"] == 0


# ---------------------------------------------------------------------------
# EmailEnricher._extract_domain
# ---------------------------------------------------------------------------

class TestExtractDomain:
    def test_extract_domain_from_company_website(self, mem_session, seed_company):
        """Extracts domain from CompanyORM.website URL."""
        enricher = EmailEnricher(mem_session, backend=ManualBackend())
        domain = enricher._extract_domain("Acme AI")
        assert domain == "www.acmeai.com"

    def test_extract_domain_fallback_to_guessed(self, mem_session):
        """When no company found, falls back to guessed domain."""
        enricher = EmailEnricher(mem_session, backend=ManualBackend())
        domain = enricher._extract_domain("Unknown Corp")
        assert domain == "unknowncorp.com"

    def test_extract_domain_strips_protocol(self, mem_session):
        """Handles URLs with or without protocol correctly."""
        company = CompanyORM(
            name="Proto Co",
            website="http://proto.co/careers",
        )
        mem_session.add(company)
        mem_session.commit()

        enricher = EmailEnricher(mem_session, backend=ManualBackend())
        domain = enricher._extract_domain("Proto Co")
        assert domain == "proto.co"
