"""Tests for Notion sync data quality fixes:

1. Multi-select pipe delimiter (round-trip with commas in tag names)
2. Timezone-aware NEWEST_WINS conflict resolution
3. File-locked sync state JSON (concurrent protection)
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, CompanyORM
from src.integrations.notion_base import NotionPropertyConverter
from src.integrations.notion_bidirectional import (
    ConflictStrategy,
    NotionBidirectionalSync,
    _parse_dt,
    _pick_winner,
    _to_utc,
)
from src.integrations.notion_incremental import NotionSyncState
from src.integrations.notion_sync import NotionSchemas, _ensure_utc, _parse_iso_utc

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def sync(db_session, tmp_path):
    return NotionBidirectionalSync(
        api_key="test-key",
        database_id="test-db-id",
        session=db_session,
        sync_state_path=str(tmp_path / "test_sync_state.json"),
    )


# ===========================================================================
# 1. Multi-select pipe delimiter tests
# ===========================================================================


class TestMultiSelectPipeDelimiter:
    """Verify pipe | is used as the multi-select delimiter, not comma."""

    def test_to_notion_splits_on_pipe(self):
        """to_notion splits ORM value on pipe, not comma."""
        result = NotionPropertyConverter.to_notion(
            "Graph RAG | Neo4j | Vector DB", "multi_select"
        )
        names = [item["name"] for item in result["multi_select"]]
        assert names == ["Graph RAG", "Neo4j", "Vector DB"]

    def test_to_notion_tag_with_comma_in_name(self):
        """A tag name containing a comma is preserved as one tag."""
        result = NotionPropertyConverter.to_notion(
            "NLP, NLU | Computer Vision | RAG, Retrieval", "multi_select"
        )
        names = [item["name"] for item in result["multi_select"]]
        assert names == ["NLP, NLU", "Computer Vision", "RAG, Retrieval"]

    def test_from_notion_joins_with_pipe(self):
        """from_notion joins multi_select items with pipe."""
        prop = {
            "type": "multi_select",
            "multi_select": [
                {"name": "Graph RAG"},
                {"name": "Neo4j"},
            ],
        }
        result = NotionPropertyConverter.from_notion(prop, "multi_select")
        assert result == "Graph RAG | Neo4j"

    def test_round_trip_with_comma_in_tag_name(self):
        """A tag name with a comma survives ORM -> Notion -> ORM round-trip."""
        original_orm_value = "NLP, NLU | Computer Vision"

        # ORM -> Notion
        notion_props = NotionPropertyConverter.to_notion(
            original_orm_value, "multi_select"
        )
        assert len(notion_props["multi_select"]) == 2
        assert notion_props["multi_select"][0]["name"] == "NLP, NLU"
        assert notion_props["multi_select"][1]["name"] == "Computer Vision"

        # Notion -> ORM
        notion_page_prop = {
            "type": "multi_select",
            "multi_select": notion_props["multi_select"],
        }
        back_to_orm = NotionPropertyConverter.from_notion(
            notion_page_prop, "multi_select"
        )
        assert back_to_orm == original_orm_value

    def test_round_trip_via_schemas(self):
        """Full round-trip through NotionSchemas.orm_to_notion + notion_to_dict."""
        company = CompanyORM(
            name="TestCo",
            differentiators="Agentic AI, Orchestration | Graph RAG",
        )
        props = NotionSchemas.orm_to_notion(company)
        ms = props["Differentiators"]["multi_select"]
        assert len(ms) == 2
        assert ms[0]["name"] == "Agentic AI, Orchestration"
        assert ms[1]["name"] == "Graph RAG"

        # Simulate Notion page response
        page = {
            "id": "page-1",
            "last_edited_time": "2026-03-10T00:00:00.000Z",
            "properties": {
                "Company": {
                    "type": "title",
                    "title": [{"plain_text": "TestCo"}],
                },
                "Differentiators": {
                    "type": "multi_select",
                    "multi_select": ms,
                },
            },
        }
        result = NotionSchemas.notion_to_dict(page)
        assert result["differentiators"] == "Agentic AI, Orchestration | Graph RAG"

    def test_single_tag_no_pipe(self):
        """A single tag without pipe produces one multi_select entry."""
        result = NotionPropertyConverter.to_notion("Solo Tag", "multi_select")
        assert len(result["multi_select"]) == 1
        assert result["multi_select"][0]["name"] == "Solo Tag"

    def test_empty_multi_select(self):
        """Empty string produces None (omitted field)."""
        result = NotionPropertyConverter.to_notion("", "multi_select")
        assert result is None

    def test_from_notion_empty_list(self):
        """Empty multi_select list from Notion returns empty string."""
        prop = {"type": "multi_select", "multi_select": []}
        result = NotionPropertyConverter.from_notion(prop, "multi_select")
        assert result == ""


# ===========================================================================
# 2. Timezone-aware NEWEST_WINS tests
# ===========================================================================


class TestTimezoneAwareNewestWins:
    """Verify NEWEST_WINS compares UTC-normalised datetimes correctly."""

    def test_to_utc_naive_assumed_utc(self):
        """Naive datetime is assumed UTC."""
        naive = datetime(2026, 3, 10, 12, 0, 0)
        result = _to_utc(naive)
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_to_utc_already_utc(self):
        """UTC-aware datetime stays UTC."""
        aware = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
        result = _to_utc(aware)
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_to_utc_converts_offset(self):
        """Non-UTC aware datetime is converted to UTC."""
        # UTC+5 at 17:00 = UTC 12:00
        offset = timezone(timedelta(hours=5))
        aware = datetime(2026, 3, 10, 17, 0, 0, tzinfo=offset)
        result = _to_utc(aware)
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_parse_dt_notion_format(self):
        """Notion Z-suffix is parsed as UTC."""
        result = _parse_dt("2026-03-10T12:00:00.000Z")
        assert result is not None
        assert result.tzinfo is not None  # should be aware

    def test_parse_dt_offset_format(self):
        """ISO timestamp with offset is parsed correctly."""
        result = _parse_dt("2026-03-10T17:00:00+05:00")
        assert result is not None

    def test_pick_winner_notion_utc_vs_local_naive(self):
        """Notion UTC newer than local naive (assumed UTC) -> Notion wins."""
        conflict = {
            "local_updated": "2026-03-10T10:00:00",      # naive, assumed UTC 10:00
            "notion_updated": "2026-03-10T12:00:00.000Z",  # UTC 12:00
        }
        assert _pick_winner(conflict, ConflictStrategy.NEWEST_WINS) == "notion"

    def test_pick_winner_local_naive_newer(self):
        """Local naive (assumed UTC) newer than Notion UTC -> Local wins."""
        conflict = {
            "local_updated": "2026-03-10T14:00:00",       # naive, assumed UTC 14:00
            "notion_updated": "2026-03-10T12:00:00.000Z",  # UTC 12:00
        }
        assert _pick_winner(conflict, ConflictStrategy.NEWEST_WINS) == "local"

    def test_pick_winner_notion_with_offset(self):
        """Notion timestamp with non-UTC offset is normalised before comparison."""
        # Notion: UTC+5 at 17:00 = UTC 12:00
        # Local: naive 14:00 = assumed UTC 14:00
        conflict = {
            "local_updated": "2026-03-10T14:00:00",
            "notion_updated": "2026-03-10T17:00:00+05:00",  # UTC 12:00
        }
        # local (14:00 UTC) > notion (12:00 UTC) -> local wins
        assert _pick_winner(conflict, ConflictStrategy.NEWEST_WINS) == "local"

    def test_pick_winner_tie_goes_to_local(self):
        """When timestamps are exactly equal, local wins (>= comparison)."""
        conflict = {
            "local_updated": "2026-03-10T12:00:00",
            "notion_updated": "2026-03-10T12:00:00.000Z",
        }
        assert _pick_winner(conflict, ConflictStrategy.NEWEST_WINS) == "local"

    def test_parse_iso_utc_notion_z(self):
        """_parse_iso_utc handles Notion Z-suffix."""
        result = _parse_iso_utc("2026-03-10T12:00:00.000Z")
        assert result is not None
        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_parse_iso_utc_empty(self):
        """_parse_iso_utc returns None for empty string."""
        assert _parse_iso_utc("") is None

    def test_ensure_utc_naive(self):
        """_ensure_utc stamps naive datetime with UTC."""
        naive = datetime(2026, 3, 10, 12, 0, 0)
        result = _ensure_utc(naive)
        assert result.tzinfo == UTC

    def test_merge_with_timezone_edge_case(self, sync, db_session):
        """NEWEST_WINS correctly picks Notion when it has UTC offset > local naive."""
        company = CompanyORM(
            name="TzTest Corp",
            updated_at=datetime(2026, 3, 10, 10, 0, 0),  # naive, assumed UTC 10:00
            tier="Tier 2",
        )
        db_session.add(company)
        db_session.commit()

        conflicts = [
            {
                "company_name": "TzTest Corp",
                "field": "tier",
                "local_value": "Tier 2",
                "notion_value": "Tier 1",
                "local_updated": "2026-03-10T10:00:00",       # UTC 10:00
                "notion_updated": "2026-03-10T12:00:00.000Z",  # UTC 12:00 (newer)
            },
        ]

        stats = sync.merge(conflicts, strategy=ConflictStrategy.NEWEST_WINS)
        assert stats["notion_kept"] == 1

        company = db_session.query(CompanyORM).filter_by(name="TzTest Corp").first()
        assert company.tier == "Tier 1"


# ===========================================================================
# 3. File-locked sync state tests
# ===========================================================================


class TestFileLockingSyncState:
    """Verify fcntl.flock protection on sync state JSON."""

    def test_basic_read_write_still_works(self, tmp_path):
        """File locking does not break basic read/write behavior."""
        state = NotionSyncState(state_path=str(tmp_path / "state.json"))
        state.update_last_sync("2026-03-10T12:00:00")
        assert state.get_last_sync() == "2026-03-10T12:00:00"

    def test_locked_read_returns_data(self, tmp_path):
        """_locked_read returns parsed JSON."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"last_sync": "2026-03-10T00:00:00"}))
        state = NotionSyncState(state_path=str(path))
        data = state._locked_read()
        assert data["last_sync"] == "2026-03-10T00:00:00"

    def test_locked_write_preserves_existing_keys(self, tmp_path):
        """_locked_write preserves other keys in the JSON."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"custom_key": "value123"}))
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync("2026-03-10T15:00:00")

        data = json.loads(path.read_text())
        assert data["custom_key"] == "value123"
        assert data["last_sync"] == "2026-03-10T15:00:00"

    def test_locked_write_handles_corrupt_json(self, tmp_path):
        """_locked_write recovers from corrupt JSON in existing file."""
        path = tmp_path / "state.json"
        path.write_text("{bad json!!!")
        state = NotionSyncState(state_path=str(path))

        state.update_last_sync("2026-03-10T16:00:00")

        data = json.loads(path.read_text())
        assert data["last_sync"] == "2026-03-10T16:00:00"

    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        """Multiple threads writing simultaneously should not corrupt the file."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))
        errors = []
        num_threads = 10
        iterations_per_thread = 5

        def writer(thread_id):
            try:
                for i in range(iterations_per_thread):
                    ts = f"2026-03-10T{thread_id:02d}:{i:02d}:00"
                    state.update_last_sync(ts)
                    # Small delay to increase chance of contention
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e}")

        threads = [
            threading.Thread(target=writer, args=(tid,))
            for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent write errors: {errors}"

        # File should still be valid JSON
        data = json.loads(path.read_text())
        assert "last_sync" in data
        assert "updated_at" in data

    def test_concurrent_read_write_no_corruption(self, tmp_path):
        """Readers and writers running concurrently produce valid state."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))
        state.update_last_sync("2026-03-10T00:00:00")

        read_results = []
        errors = []

        def reader():
            try:
                for _ in range(10):
                    result = state.get_last_sync()
                    if result is not None:
                        read_results.append(result)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Reader: {e}")

        def writer():
            try:
                for i in range(10):
                    state.update_last_sync(f"2026-03-10T{i:02d}:00:00")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"Writer: {e}")

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent errors: {errors}"
        # All reads should have returned valid timestamps
        for r in read_results:
            assert isinstance(r, str)
            assert "2026" in r

    def test_creates_parent_dirs_with_locking(self, tmp_path):
        """update_last_sync creates parent directories even with locking."""
        path = tmp_path / "nested" / "deep" / "state.json"
        state = NotionSyncState(state_path=str(path))
        state.update_last_sync("2026-03-10T12:00:00")
        assert path.exists()
        assert state.get_last_sync() == "2026-03-10T12:00:00"

    def test_get_last_sync_no_file_returns_none(self, tmp_path):
        """get_last_sync returns None when no file exists (no lock needed)."""
        state = NotionSyncState(state_path=str(tmp_path / "missing.json"))
        assert state.get_last_sync() is None

    def test_reset_after_locked_write(self, tmp_path):
        """reset works correctly after a locked write."""
        path = tmp_path / "state.json"
        state = NotionSyncState(state_path=str(path))
        state.update_last_sync("2026-03-10T12:00:00")
        assert state.get_last_sync() is not None
        state.reset()
        assert state.get_last_sync() is None
        assert not path.exists()
