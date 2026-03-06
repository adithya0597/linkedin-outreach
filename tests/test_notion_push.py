"""Tests for Notion push_updates and sync timestamps in NotionBidirectionalSync."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM
from src.integrations.notion_bidirectional import NotionBidirectionalSync


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


def _add_company(
    session,
    name: str,
    updated_at: datetime | None = None,
    last_synced_at: datetime | None = None,
    **fields,
) -> CompanyORM:
    """Insert a CompanyORM row into the test DB."""
    company = CompanyORM(
        name=name,
        updated_at=updated_at or datetime(2026, 3, 5, 10, 0, 0),
        last_synced_at=last_synced_at,
        **fields,
    )
    session.add(company)
    session.commit()
    return company


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPushUpdatesUnsyncedRecords:
    """Unsynced records (last_synced_at is None) are found by push_updates."""

    @pytest.mark.asyncio
    async def test_unsynced_records_are_pushed(self, sync, db_session):
        """Records with last_synced_at=None should be identified and pushed."""
        _add_company(
            db_session,
            "Acme AI",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
            tier="Tier 1",
        )
        _add_company(
            db_session,
            "Beta Corp",
            updated_at=datetime(2026, 3, 5, 14, 0, 0),
            last_synced_at=None,
            tier="Tier 2",
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.push_updates(dry_run=False)

        assert result["pushed"] == 2
        assert result["push_errors"] == []
        assert result["skipped"] == 0


class TestSyncedRecordsSkipped:
    """Synced records (last_synced_at > updated_at) are skipped by push_updates."""

    @pytest.mark.asyncio
    async def test_already_synced_records_are_skipped(self, sync, db_session):
        """Records where last_synced_at >= updated_at should not be pushed."""
        _add_company(
            db_session,
            "Already Synced Corp",
            updated_at=datetime(2026, 3, 5, 10, 0, 0),
            last_synced_at=datetime(2026, 3, 5, 12, 0, 0),  # synced AFTER update
            tier="Tier 1",
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ) as mock_sync:
            result = await sync.push_updates(dry_run=False)

        assert result["pushed"] == 0
        mock_sync.assert_not_called()


class TestDryRunCountsOnly:
    """Dry run counts records but doesn't push to Notion."""

    @pytest.mark.asyncio
    async def test_dry_run_counts_without_pushing(self, sync, db_session):
        """dry_run=True should count dirty records but not call sync_company."""
        _add_company(
            db_session,
            "DryRun Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
        )
        _add_company(
            db_session,
            "DryRun Corp 2",
            updated_at=datetime(2026, 3, 5, 14, 0, 0),
            last_synced_at=datetime(2026, 3, 5, 10, 0, 0),  # stale sync
        )

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock
        ) as mock_sync:
            result = await sync.push_updates(dry_run=True)

        assert result["pushed"] == 2
        assert result["push_errors"] == []
        mock_sync.assert_not_called()

        # Verify last_synced_at was NOT updated
        for company in db_session.query(CompanyORM).all():
            if company.name == "DryRun Corp":
                assert company.last_synced_at is None
            elif company.name == "DryRun Corp 2":
                assert company.last_synced_at == datetime(2026, 3, 5, 10, 0, 0)


class TestFullSyncIncludesPushStats:
    """full_sync includes push stats (pushed, push_errors) in its result dict."""

    @pytest.mark.asyncio
    async def test_full_sync_returns_push_stats(self, sync, db_session):
        """full_sync result dict should contain pushed and push_errors keys."""
        _add_company(
            db_session,
            "PushMe Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
            tier="Tier 2",
        )

        fake_records = [
            {
                "name": "PushMe Corp",
                "_notion_page_id": "page-pushme",
                "_notion_updated": "2026-03-05T10:00:00.000Z",
                "tier": "Tier 2",
            },
        ]

        with patch.object(
            sync.notion, "pull_all", new_callable=AsyncMock, return_value=fake_records
        ), patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.full_sync(dry_run=False)

        assert "pushed" in result
        assert "push_errors" in result
        assert isinstance(result["pushed"], int)
        assert isinstance(result["push_errors"], list)
        assert result["pushed"] >= 1


class TestLastSyncedAtUpdatedAfterPush:
    """last_synced_at is updated after a successful push."""

    @pytest.mark.asyncio
    async def test_last_synced_at_stamped_on_success(self, sync, db_session):
        """After a successful push, last_synced_at should be set to ~now."""
        company = _add_company(
            db_session,
            "Stamp Corp",
            updated_at=datetime(2026, 3, 5, 12, 0, 0),
            last_synced_at=None,
        )

        before_push = datetime.now()

        with patch.object(
            sync.notion, "sync_company", new_callable=AsyncMock, return_value="page-id"
        ):
            result = await sync.push_updates(dry_run=False)

        after_push = datetime.now()

        assert result["pushed"] == 1

        # Refresh from DB
        db_session.refresh(company)
        assert company.last_synced_at is not None
        assert before_push <= company.last_synced_at <= after_push


class TestCompanyORMHasLastSyncedAt:
    """CompanyORM has the last_synced_at column."""

    def test_last_synced_at_column_exists(self, db_session):
        """CompanyORM should have a last_synced_at column that defaults to None."""
        company = CompanyORM(name="Schema Test Corp")
        db_session.add(company)
        db_session.commit()

        fetched = db_session.query(CompanyORM).filter_by(name="Schema Test Corp").first()
        assert fetched is not None
        assert hasattr(fetched, "last_synced_at")
        assert fetched.last_synced_at is None

    def test_last_synced_at_can_be_set(self, db_session):
        """last_synced_at can be set to a datetime value."""
        now = datetime(2026, 3, 6, 10, 0, 0)
        company = CompanyORM(name="Timestamp Corp", last_synced_at=now)
        db_session.add(company)
        db_session.commit()

        fetched = db_session.query(CompanyORM).filter_by(name="Timestamp Corp").first()
        assert fetched.last_synced_at == now
