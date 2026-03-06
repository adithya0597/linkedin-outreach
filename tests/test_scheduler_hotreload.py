"""Tests for scheduler config hot-reload."""

import os
import tempfile
import time

import yaml
import pytest

from src.pipeline.scheduler import ScanScheduler


@pytest.fixture
def config_file():
    """Create a temporary config file for testing."""
    config = {
        "schedules": {
            "full_scan": {"cron": "0 8 * * *", "portals": "all"},
            "afternoon_rescan": {
                "cron": "0 14 * * *",
                "portals": ["wellfound", "linkedin"],
            },
        },
        "promotion_rules": {
            "promote_threshold": 4,
            "demote_threshold": 3,
            "review_window_weeks": 2,
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(config, f)
        f.flush()
        yield f.name
    os.unlink(f.name)


class TestMaybeReloadConfig:
    def test_no_reload_when_unchanged(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        assert scheduler._maybe_reload_config() is False

    def test_reload_when_file_modified(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        # Wait a bit to ensure mtime differs
        time.sleep(0.05)
        # Modify the file
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "schedules": {
                        "full_scan": {"cron": "0 9 * * *", "portals": "all"},
                        "afternoon_rescan": {
                            "cron": "0 15 * * *",
                            "portals": ["wellfound"],
                        },
                    },
                },
                f,
            )
        assert scheduler._maybe_reload_config() is True
        # Verify new config was loaded
        assert scheduler.config["schedules"]["full_scan"]["cron"] == "0 9 * * *"

    def test_scheduler_works_after_reload(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        time.sleep(0.05)
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "schedules": {
                        "full_scan": {"cron": "0 7 * * *", "portals": "all"},
                        "afternoon_rescan": {
                            "cron": "0 14 * * *",
                            "portals": ["yc", "builtin"],
                        },
                    },
                },
                f,
            )
        scheduler._maybe_reload_config()
        assert scheduler.get_rescan_portals() == ["yc", "builtin"]

    def test_reload_handles_missing_file(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        # Remove the file
        os.unlink(config_file)
        # Should return False without raising
        assert scheduler._maybe_reload_config() is False
        # Recreate so fixture cleanup doesn't fail
        with open(config_file, "w") as f:
            yaml.dump({"schedules": {}}, f)

    def test_reload_handles_invalid_yaml(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        original_config = scheduler.config.copy()
        time.sleep(0.05)
        # Write invalid YAML
        with open(config_file, "w") as f:
            f.write("{{{{invalid yaml: [[[")
        # Should return False and keep old config
        assert scheduler._maybe_reload_config() is False
        assert scheduler.config == original_config

    def test_mtime_tracking_is_correct(self, config_file):
        scheduler = ScanScheduler(config_path=config_file)
        initial_mtime = scheduler._config_mtime
        assert initial_mtime == os.path.getmtime(config_file)
        # After reload, mtime should update
        time.sleep(0.05)
        with open(config_file, "w") as f:
            yaml.dump(
                {
                    "schedules": {
                        "full_scan": {"cron": "0 6 * * *", "portals": "all"},
                        "afternoon_rescan": {
                            "cron": "0 14 * * *",
                            "portals": ["wellfound"],
                        },
                    },
                },
                f,
            )
        scheduler._maybe_reload_config()
        assert scheduler._config_mtime > initial_mtime
