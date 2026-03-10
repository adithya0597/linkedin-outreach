"""Tests for H1B enrichment: parse_h1b_status enhancements and apply_known_statuses."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.enums import H1BStatus
from src.db.h1b_lookup import KNOWN_H1B_STATUSES, apply_known_statuses
from src.db.orm import Base, CompanyORM
from src.db.seed import parse_h1b_status

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_engine():
    """In-memory SQLite engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mem_session(mem_engine):
    """Session backed by in-memory SQLite."""
    factory = sessionmaker(bind=mem_engine)
    sess = factory()
    yield sess
    sess.close()


# ---------------------------------------------------------------------------
# parse_h1b_status — new Frog Hire patterns
# ---------------------------------------------------------------------------

class TestParseH1BStatusFrogHire:
    def test_frog_hire_lowercase(self):
        assert parse_h1b_status("frog hire confirmed") == H1BStatus.CONFIRMED

    def test_frog_hire_mixed_case(self):
        assert parse_h1b_status("Frog Hire: H1B + PERM + EVerify") == H1BStatus.CONFIRMED

    def test_frog_hire_in_sentence(self):
        assert parse_h1b_status("Verified via Frog Hire database") == H1BStatus.CONFIRMED

    def test_h1b_plus_perm(self):
        assert parse_h1b_status("H1B+PERM supported") == H1BStatus.CONFIRMED

    def test_h1b_plus_perm_lowercase(self):
        assert parse_h1b_status("h1b+perm") == H1BStatus.CONFIRMED

    def test_h1b_sponsor(self):
        assert parse_h1b_status("H1B Sponsor available") == H1BStatus.CONFIRMED

    def test_h1b_sponsor_lowercase(self):
        assert parse_h1b_status("offers h1b sponsorship") == H1BStatus.CONFIRMED


# ---------------------------------------------------------------------------
# parse_h1b_status — backward compatibility
# ---------------------------------------------------------------------------

class TestParseH1BStatusBackwardCompat:
    def test_confirmed_keyword(self):
        assert parse_h1b_status("Confirmed") == H1BStatus.CONFIRMED

    def test_checkmark_emoji(self):
        assert parse_h1b_status("H1B ✅") == H1BStatus.CONFIRMED

    def test_likely(self):
        assert parse_h1b_status("Likely (cross-check needed)") == H1BStatus.LIKELY

    def test_explicit_no(self):
        assert parse_h1b_status("explicit no sponsorship") == H1BStatus.EXPLICIT_NO

    def test_does_not_sponsor(self):
        assert parse_h1b_status("Does NOT sponsor H1B") == H1BStatus.EXPLICIT_NO

    def test_not_applicable(self):
        assert parse_h1b_status("N/A (Tier 3 — startup portal)") == H1BStatus.NOT_APPLICABLE

    def test_unknown_default(self):
        assert parse_h1b_status("") == H1BStatus.UNKNOWN

    def test_unknown_random_text(self):
        assert parse_h1b_status("some random text") == H1BStatus.UNKNOWN


# ---------------------------------------------------------------------------
# apply_known_statuses — updates Unknown companies
# ---------------------------------------------------------------------------

class TestApplyKnownStatusesUpdates:
    def test_updates_unknown_to_confirmed(self, mem_session):
        """A company in KNOWN_H1B_STATUSES with Confirmed should be updated."""
        company = CompanyORM(name="LlamaIndex", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 1
        mem_session.refresh(company)
        assert company.h1b_status == "Confirmed"
        assert "Frog Hire" in company.h1b_source

    def test_updates_unknown_to_likely(self, mem_session):
        """LangChain should be updated to Likely."""
        company = CompanyORM(name="LangChain", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 1
        mem_session.refresh(company)
        assert company.h1b_status == "Likely"

    def test_skips_already_confirmed(self, mem_session):
        """A company already Confirmed should not be touched."""
        company = CompanyORM(
            name="Cursor",
            h1b_status="Confirmed",
            h1b_source="Original source",
        )
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 0
        mem_session.refresh(company)
        assert company.h1b_source == "Original source"

    def test_skips_known_unknown_status(self, mem_session):
        """Kumo AI is in lookup as Unknown -- should NOT be updated."""
        company = CompanyORM(name="Kumo AI", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 0
        mem_session.refresh(company)
        assert company.h1b_status == "Unknown"


# ---------------------------------------------------------------------------
# apply_known_statuses — case insensitive matching
# ---------------------------------------------------------------------------

class TestApplyKnownStatusesCaseInsensitive:
    def test_lowercase_name(self, mem_session):
        company = CompanyORM(name="llamaindex", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 1
        mem_session.refresh(company)
        assert company.h1b_status == "Confirmed"

    def test_uppercase_name(self, mem_session):
        company = CompanyORM(name="SNORKEL AI", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 1
        mem_session.refresh(company)
        assert company.h1b_status == "Confirmed"

    def test_mixed_case_name(self, mem_session):
        company = CompanyORM(name="hippocratic ai", h1b_status="Unknown")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 1
        mem_session.refresh(company)
        assert company.h1b_status == "Confirmed"


# ---------------------------------------------------------------------------
# apply_known_statuses — multiple companies
# ---------------------------------------------------------------------------

class TestApplyKnownStatusesMultiple:
    def test_only_known_companies_updated(self, mem_session):
        """Mix of known and unknown companies -- only known ones with non-Unknown status updated."""
        companies = [
            CompanyORM(name="LlamaIndex", h1b_status="Unknown"),      # known -> Confirmed
            CompanyORM(name="Cinder", h1b_status="Unknown"),           # known -> Confirmed
            CompanyORM(name="RandomCo", h1b_status="Unknown"),         # NOT in lookup
            CompanyORM(name="Kumo AI", h1b_status="Unknown"),          # known but Unknown -> skip
            CompanyORM(name="Cursor", h1b_status="Confirmed"),         # already Confirmed -> skip
        ]
        for c in companies:
            mem_session.add(c)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 2  # LlamaIndex + Cinder

        # Verify individual states
        for c in companies:
            mem_session.refresh(c)

        assert companies[0].h1b_status == "Confirmed"   # LlamaIndex
        assert companies[1].h1b_status == "Confirmed"   # Cinder
        assert companies[2].h1b_status == "Unknown"      # RandomCo untouched
        assert companies[3].h1b_status == "Unknown"      # Kumo AI stays Unknown
        assert companies[4].h1b_status == "Confirmed"    # Cursor was already Confirmed

    def test_returns_zero_when_nothing_to_update(self, mem_session):
        """No Unknown companies at all -> 0."""
        company = CompanyORM(name="LlamaIndex", h1b_status="Confirmed")
        mem_session.add(company)
        mem_session.commit()

        count = apply_known_statuses(mem_session)
        assert count == 0


# ---------------------------------------------------------------------------
# KNOWN_H1B_STATUSES — data integrity
# ---------------------------------------------------------------------------

class TestKnownH1BStatusesIntegrity:
    EXPECTED_COMPANIES = [
        "Kumo AI",
        "LlamaIndex",
        "Cursor",
        "Hippocratic AI",
        "LangChain",
        "Norm AI",
        "Spherecast",
        "Cinder",
        "Augment Code",
        "Pair Team",
        "Snorkel AI",
        "EvenUp",
    ]

    VALID_STATUSES = {"Confirmed", "Likely", "Unknown", "Explicit No", "N/A"}

    def test_contains_all_expected_companies(self):
        for company in self.EXPECTED_COMPANIES:
            assert company in KNOWN_H1B_STATUSES, f"{company} missing from KNOWN_H1B_STATUSES"

    def test_has_exactly_12_entries(self):
        assert len(KNOWN_H1B_STATUSES) == 12

    def test_all_values_are_valid_statuses(self):
        for company, status in KNOWN_H1B_STATUSES.items():
            assert status in self.VALID_STATUSES, (
                f"{company} has invalid status '{status}'. "
                f"Must be one of {self.VALID_STATUSES}"
            )

    def test_no_duplicate_keys(self):
        """Dict keys are inherently unique, but verify count matches set."""
        assert len(KNOWN_H1B_STATUSES) == len(set(KNOWN_H1B_STATUSES.keys()))
