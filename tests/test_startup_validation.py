"""Tests for startup validation checks and Settings.timezone."""
import os
from unittest.mock import patch

from src.config.settings import Settings
from src.config.startup_checks import (
    CheckResult,
    run_all_checks,
    validate_api_keys,
    validate_config_files,
    validate_database,
)


class TestValidateApiKeys:
    def test_all_keys_present(self):
        env = {
            "NOTION_API_KEY": "ntn_test",
            "NOTION_DATABASE_ID": "db-123",
            "APIFY_TOKEN": "apify_test",
        }
        with patch.dict(os.environ, env, clear=False):
            results = validate_api_keys()
        assert len(results) == 3
        assert all(r.passed for r in results)

    def test_all_keys_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            results = validate_api_keys()
        assert len(results) == 3
        assert not any(r.passed for r in results)
        # Notion keys should be severity=error
        notion_results = [r for r in results if "notion" in r.name]
        assert all(r.severity == "error" for r in notion_results)
        # Apify should be severity=warning
        apify_results = [r for r in results if "apify" in r.name]
        assert all(r.severity == "warning" for r in apify_results)


class TestValidateConfigFiles:
    def test_valid_yaml(self, tmp_path, monkeypatch):
        portals = tmp_path / "config" / "portals.yaml"
        portals.parent.mkdir(parents=True)
        portals.write_text("portals:\n  - name: test\n")
        monkeypatch.chdir(tmp_path)
        results = validate_config_files()
        assert len(results) == 1
        assert results[0].passed is True

    def test_invalid_yaml(self, tmp_path, monkeypatch):
        portals = tmp_path / "config" / "portals.yaml"
        portals.parent.mkdir(parents=True)
        portals.write_text("invalid: yaml: [broken")
        monkeypatch.chdir(tmp_path)
        results = validate_config_files()
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == "error"

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        results = validate_config_files()
        assert len(results) == 1
        assert results[0].passed is False
        assert "not found" in results[0].message


class TestValidateDatabase:
    def test_database_exists(self, tmp_path, monkeypatch):
        db = tmp_path / "data" / "outreach.db"
        db.parent.mkdir(parents=True)
        db.write_text("")
        monkeypatch.chdir(tmp_path)
        results = validate_database()
        assert len(results) == 1
        assert results[0].passed is True

    def test_database_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        results = validate_database()
        assert len(results) == 1
        assert results[0].passed is False


class TestRunAllChecks:
    def test_aggregation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch.dict(os.environ, {}, clear=True):
            results = run_all_checks()
        # Should have results from all check functions
        assert len(results) >= 5  # 3 api keys + 1 config + 1 db + 1 chrome (at least)
        assert all(isinstance(r, CheckResult) for r in results)


class TestSettingsTimezone:
    def test_timezone_default(self):
        s = Settings(_env_file=None)
        assert s.timezone == "America/Chicago"

    def test_timezone_override(self, monkeypatch):
        monkeypatch.setenv("TIMEZONE", "US/Eastern")
        s = Settings(_env_file=None)
        assert s.timezone == "US/Eastern"
