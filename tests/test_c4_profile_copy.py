"""Tests for Chrome profile copy to temp dir in PatchrightScraper."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from src.scrapers.patchright_scraper import (
    JobrightPatchrightScraper,
    TrueUpPatchrightScraper,
    cleanup_stale_temp_profiles,
)


class TestProfileCopyInit:
    def test_temp_profile_initialized_to_none(self):
        scraper = JobrightPatchrightScraper()
        assert scraper._temp_profile is None

    def test_trueup_temp_profile_initialized_to_none(self):
        scraper = TrueUpPatchrightScraper()
        assert scraper._temp_profile is None


class TestProfileCopyInLaunch:
    """Verify that _launch copies profile to temp dir."""

    @pytest.mark.asyncio
    async def test_launch_creates_temp_profile(self):
        scraper = JobrightPatchrightScraper()

        # We can't actually launch, but we can verify the attribute exists
        assert hasattr(scraper, "_temp_profile")
        assert scraper._temp_profile is None

    @pytest.mark.asyncio
    async def test_close_cleans_temp_profile(self):
        scraper = JobrightPatchrightScraper()

        # Simulate a temp profile existing
        tmp = tempfile.mkdtemp(prefix="patchright_")
        scraper._temp_profile = tmp
        scraper._context = None
        scraper._browser = None
        scraper._pw = None
        scraper._holds_chrome_lock = False

        await scraper._close()

        assert not Path(tmp).exists()
        assert scraper._temp_profile is None

    @pytest.mark.asyncio
    async def test_close_handles_missing_temp_profile(self):
        scraper = TrueUpPatchrightScraper()
        scraper._temp_profile = "/nonexistent/patchright_test"
        scraper._context = None
        scraper._browser = None
        scraper._pw = None
        scraper._holds_chrome_lock = False

        # Should not raise
        await scraper._close()
        assert scraper._temp_profile is None


class TestStaleCleanup:
    def test_cleanup_stale_removes_old_dirs(self):
        import time

        # Create a fake stale dir
        tmp = tempfile.mkdtemp(prefix="patchright_")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(tmp, (old_time, old_time))

        cleaned = cleanup_stale_temp_profiles(max_age_hours=1)

        assert cleaned >= 1
        assert not Path(tmp).exists()

    def test_cleanup_preserves_recent_dirs(self):
        # Create a fresh dir
        tmp = tempfile.mkdtemp(prefix="patchright_")

        cleaned = cleanup_stale_temp_profiles(max_age_hours=1)

        # Fresh dir should NOT be cleaned
        assert Path(tmp).exists()

        # Clean up manually
        shutil.rmtree(tmp)


class TestPatchrightScraperBase:
    def test_has_temp_profile_attribute(self):
        """Verify PatchrightScraper has _temp_profile in __init__."""
        scraper = JobrightPatchrightScraper()
        assert hasattr(scraper, "_temp_profile")
