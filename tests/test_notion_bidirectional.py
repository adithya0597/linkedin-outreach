"""Tests for NotionBidirectionalSync — conflict detection and merge strategies."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM
from src.integrations.notion_bidirectional import (
    ConflictStrategy,
    NotionBidirectionalSync,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite session with the schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def sync(db_session, tmp_path):
    """Return a NotionBidirectionalSync wired to the test session."""
    return NotionBidirectionalSync(
        api_key="test-key",
        database_id="test-db-id",
        session=db_session,
        sync_state_path=str(tmp_path / "test_sync_state.json"),
    )


def _make_notion_record(
    name: str,
    updated: str = "2026-03-05T12:00:00.000Z",
    **fields,
) -> dict:
    """Helper to build a dict mimicking NotionCRM.pull_all() output."""
    record = {
        "name": name,
        "_notion_page_id": f"page-{name.lower().replace(' ', '-')}",
        "_notion_updated": updated,
    }
    record.update(fields)
    return record


def _add_local_company(
    session,
    name: str,
    updated_at: datetime | None = None,
    **fields,
) -> CompanyORM:
    """Insert a CompanyORM into the test DB."""
    company = CompanyORM(
        name=name,
        updated_at=updated_at or datetime(2026, 3, 5, 10, 0, 0),
        **fields,
    )
    session.add(company)
    session.commit()
    return company


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_updates_converts_notion_pages(sync):
    """pull_updates calls NotionCRM.pull_all and returns its result."""
    fake_records = [
        _make_notion_record("Acme AI", tier="Tier 1"),
        _make_notion_record("Beta Corp", tier="Tier 2"),
    ]

    with patch.object(sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records):
        result = await sync.pull_updates()

    assert len(result) == 2
    assert result[0]["name"] == "Acme AI"
    assert result[0]["_notion_page_id"] == "page-acme-ai"
    assert result[1]["tier"] == "Tier 2"


def test_detect_conflicts_finds_changed_fields(sync, db_session):
    """When both local and Notion changed the same field, a conflict is detected."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
        stage="To apply",
    )

    pulled = [
        _make_notion_record(
            "Acme AI",
            updated="2026-03-05T14:00:00.000Z",
            tier="Tier 1",
            stage="Applied",
        ),
    ]

    conflicts = sync.detect_conflicts(pulled)

    field_names = {c["field"] for c in conflicts}
    assert "tier" in field_names
    assert "stage" in field_names
    # Each conflict dict should have all required keys
    for c in conflicts:
        assert c["company_name"] == "Acme AI"
        assert "local_value" in c
        assert "notion_value" in c


def test_no_conflict_when_only_one_side_changed(sync, db_session):
    """If values match, no conflict is reported even if timestamps differ."""
    _add_local_company(
        db_session,
        "Same Corp",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 1",
        stage="To apply",
    )

    pulled = [
        _make_notion_record(
            "Same Corp",
            updated="2026-03-05T14:00:00.000Z",
            tier="Tier 1",
            stage="To apply",
        ),
    ]

    conflicts = sync.detect_conflicts(pulled)
    assert len(conflicts) == 0


def test_local_wins_keeps_local_values(sync, db_session):
    """LOCAL_WINS strategy keeps local values for all conflicts."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
    )

    conflicts = [
        {
            "company_name": "Acme AI",
            "field": "tier",
            "local_value": "Tier 2",
            "notion_value": "Tier 1",
            "local_updated": "2026-03-05T10:00:00",
            "notion_updated": "2026-03-05T14:00:00",
        },
    ]

    stats = sync.merge(conflicts, strategy=ConflictStrategy.LOCAL_WINS)

    assert stats["local_kept"] == 1
    assert stats["notion_kept"] == 0
    assert stats["merged"] == 1

    company = db_session.query(CompanyORM).filter_by(name="Acme AI").first()
    assert company.tier == "Tier 2"


def test_notion_wins_keeps_notion_values(sync, db_session):
    """NOTION_WINS strategy overwrites local with Notion values."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
    )

    conflicts = [
        {
            "company_name": "Acme AI",
            "field": "tier",
            "local_value": "Tier 2",
            "notion_value": "Tier 1",
            "local_updated": "2026-03-05T10:00:00",
            "notion_updated": "2026-03-05T14:00:00",
        },
    ]

    stats = sync.merge(conflicts, strategy=ConflictStrategy.NOTION_WINS)

    assert stats["notion_kept"] == 1
    assert stats["local_kept"] == 0

    company = db_session.query(CompanyORM).filter_by(name="Acme AI").first()
    assert company.tier == "Tier 1"


def test_newest_wins_picks_by_timestamp(sync, db_session):
    """NEWEST_WINS picks whichever side has the more recent timestamp."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
        stage="Applied",
    )

    conflicts = [
        {
            "company_name": "Acme AI",
            "field": "tier",
            "local_value": "Tier 2",
            "notion_value": "Tier 1",
            "local_updated": "2026-03-05T10:00:00",  # older
            "notion_updated": "2026-03-05T14:00:00",  # newer -> Notion wins
        },
        {
            "company_name": "Acme AI",
            "field": "stage",
            "local_value": "Applied",
            "notion_value": "To apply",
            "local_updated": "2026-03-05T16:00:00",  # newer -> Local wins
            "notion_updated": "2026-03-05T14:00:00",  # older
        },
    ]

    stats = sync.merge(conflicts, strategy=ConflictStrategy.NEWEST_WINS)

    assert stats["merged"] == 2
    assert stats["notion_kept"] == 1
    assert stats["local_kept"] == 1

    company = db_session.query(CompanyORM).filter_by(name="Acme AI").first()
    assert company.tier == "Tier 1"  # Notion won (newer)
    assert company.stage == "Applied"  # Local won (newer)


@pytest.mark.asyncio
async def test_dry_run_returns_conflicts_without_merging(sync, db_session):
    """dry_run=True detects conflicts but does not alter local DB."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
    )

    fake_records = [
        _make_notion_record("Acme AI", updated="2026-03-05T14:00:00.000Z", tier="Tier 1"),
    ]

    with patch.object(sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records):
        result = await sync.full_sync(strategy=ConflictStrategy.NEWEST_WINS, dry_run=True)

    assert result["dry_run"] is True
    assert result["conflicts_found"] >= 1
    assert result["merged"] == 0

    # Local value unchanged
    company = db_session.query(CompanyORM).filter_by(name="Acme AI").first()
    assert company.tier == "Tier 2"


@pytest.mark.asyncio
async def test_full_sync_pipeline(sync, db_session):
    """full_sync runs pull -> detect -> merge end to end."""
    _add_local_company(
        db_session,
        "Acme AI",
        updated_at=datetime(2026, 3, 5, 10, 0, 0),
        tier="Tier 2",
    )

    fake_records = [
        _make_notion_record("Acme AI", updated="2026-03-05T14:00:00.000Z", tier="Tier 1"),
    ]

    with patch.object(sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records), \
         patch.object(sync.notion, "push_all_parallel", new_callable=AsyncMock, return_value=["page-id"]):
        result = await sync.full_sync(strategy=ConflictStrategy.NOTION_WINS)

    assert result["pulled"] == 1
    assert result["conflicts_found"] >= 1
    assert result["merged"] >= 1
    assert result["strategy_used"] == ConflictStrategy.NOTION_WINS

    company = db_session.query(CompanyORM).filter_by(name="Acme AI").first()
    assert company.tier == "Tier 1"


@pytest.mark.asyncio
async def test_handles_company_not_in_local_db(sync, db_session):
    """A Notion record with no local match should create a new CompanyORM."""
    fake_records = [
        _make_notion_record("New Startup", updated="2026-03-05T14:00:00.000Z", tier="Tier 3"),
    ]

    with patch.object(sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records), \
         patch.object(sync.notion, "push_all_parallel", new_callable=AsyncMock, return_value=["page-id"]):
        result = await sync.full_sync(strategy=ConflictStrategy.NEWEST_WINS)

    assert result["new_companies"] == 1
    assert result["conflicts_found"] == 0

    company = db_session.query(CompanyORM).filter_by(name="New Startup").first()
    assert company is not None
    assert company.tier == "Tier 3"


def test_handles_company_not_in_notion(sync, db_session):
    """A local company with no matching Notion record produces no conflict."""
    _add_local_company(db_session, "Local Only Corp", tier="Tier 1")

    pulled = [
        _make_notion_record("Other Company", updated="2026-03-05T14:00:00.000Z"),
    ]

    conflicts = sync.detect_conflicts(pulled)
    local_only_conflicts = [c for c in conflicts if c["company_name"] == "Local Only Corp"]
    assert len(local_only_conflicts) == 0
