"""Tests for NotionCRM batch sync -- parallel push and incremental pull."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.orm import CompanyORM
from src.integrations.notion_sync import NotionCRM


class TestPushAllParallel:
    """Verify semaphore-limited parallel push behaviour."""

    @pytest.fixture
    def crm(self):
        return NotionCRM(api_key="test-key", database_id="test-db-id")

    @pytest.fixture
    def companies(self):
        return [
            CompanyORM(name="Company A"),
            CompanyORM(name="Company B"),
            CompanyORM(name="Company C"),
        ]

    @pytest.mark.asyncio
    async def test_push_all_parallel_calls_push_for_each(self, crm, companies):
        """push_all_parallel calls sync_company for each company."""
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = ["page-a", "page-b", "page-c"]
            results = await crm.push_all_parallel(companies, max_concurrent=3)

        assert mock_sync.call_count == 3
        assert results == ["page-a", "page-b", "page-c"]

    @pytest.mark.asyncio
    async def test_push_all_parallel_respects_max_concurrent(self, crm, companies):
        """push_all_parallel never exceeds max_concurrent in-flight pushes."""
        max_concurrent = 2
        active_count = 0
        max_observed = 0

        original_sync = AsyncMock(side_effect=["p1", "p2", "p3"])

        async def tracking_sync(company):
            nonlocal active_count, max_observed
            active_count += 1
            max_observed = max(max_observed, active_count)
            result = await original_sync(company)
            await asyncio.sleep(0.01)  # simulate work
            active_count -= 1
            return result

        with patch.object(crm, "sync_company", side_effect=tracking_sync):
            results = await crm.push_all_parallel(
                companies, max_concurrent=max_concurrent
            )

        assert max_observed <= max_concurrent
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_push_all_parallel_handles_errors_gracefully(self, crm, companies):
        """One failure does not stop other pushes from succeeding."""
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = [
                "page-a",
                Exception("API error"),
                "page-c",
            ]
            results = await crm.push_all_parallel(companies, max_concurrent=3)

        # Only successful pushes are in results
        assert "page-a" in results
        assert "page-c" in results
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_push_all_parallel_returns_page_ids(self, crm, companies):
        """push_all_parallel returns a list of page ID strings."""
        with patch.object(crm, "sync_company", new_callable=AsyncMock) as mock_sync:
            mock_sync.side_effect = ["id-1", "id-2", "id-3"]
            results = await crm.push_all_parallel(companies)

        assert results == ["id-1", "id-2", "id-3"]
        for r in results:
            assert isinstance(r, str)

    @pytest.mark.asyncio
    async def test_push_all_parallel_empty_list(self, crm):
        """push_all_parallel with empty list returns empty results."""
        results = await crm.push_all_parallel([], max_concurrent=3)
        assert results == []


class TestPullSince:
    """Verify incremental pull with last_edited_time filter."""

    @pytest.fixture
    def crm(self):
        return NotionCRM(api_key="test-key", database_id="test-db-id")

    @pytest.mark.asyncio
    async def test_pull_since_builds_correct_filter(self, crm):
        """pull_since sends the correct Notion filter payload."""
        timestamp = "2026-03-05T12:00:00"
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": []}
            await crm.pull_since(timestamp)

        mock_req.assert_called_once()
        call_args = mock_req.call_args
        payload = call_args[1]["json"]
        assert payload["filter"]["timestamp"] == "last_edited_time"
        assert payload["filter"]["last_edited_time"]["after"] == timestamp

    @pytest.mark.asyncio
    async def test_pull_since_returns_pages(self, crm):
        """pull_since returns the results list from Notion response."""
        pages = [
            {"id": "page-1", "properties": {}},
            {"id": "page-2", "properties": {}},
        ]
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": pages}
            result = await crm.pull_since("2026-03-05T12:00:00")

        assert len(result) == 2
        assert result[0]["id"] == "page-1"
        assert result[1]["id"] == "page-2"

    @pytest.mark.asyncio
    async def test_pull_since_no_results_returns_empty(self, crm):
        """pull_since returns empty list when no pages match."""
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"results": []}
            result = await crm.pull_since("2026-03-06T00:00:00")

        assert result == []

    @pytest.mark.asyncio
    async def test_pull_since_handles_api_error(self, crm):
        """pull_since returns empty list on API error instead of raising."""
        with patch.object(crm, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = Exception("Network error")
            result = await crm.pull_since("2026-03-05T12:00:00")

        assert result == []


class TestIncrementalPullIntegration:
    """Integration-style test: incremental pull uses sync state timestamp."""

    @pytest.mark.asyncio
    async def test_incremental_pull_uses_sync_state(self, tmp_path):
        """When sync state has a timestamp, pull_since is called with it."""
        from src.integrations.notion_incremental import NotionSyncState

        state_path = str(tmp_path / "sync_state.json")
        state = NotionSyncState(state_path=state_path)
        state.update_last_sync("2026-03-05T10:00:00")

        crm = NotionCRM(api_key="test-key", database_id="test-db-id")

        with patch.object(crm, "pull_since", new_callable=AsyncMock) as mock_pull:
            mock_pull.return_value = [{"id": "page-1"}]

            last_sync = state.get_last_sync()
            assert last_sync is not None
            result = await crm.pull_since(last_sync)

        mock_pull.assert_called_once_with("2026-03-05T10:00:00")
        assert len(result) == 1
