"""Tests for Alembic migration setup."""

import configparser
import importlib
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent


class TestAlembicFiles:
    """Verify the Alembic scaffolding files exist and are correct."""

    def test_alembic_ini_exists_and_has_script_location(self):
        ini_path = ROOT / "alembic.ini"
        assert ini_path.exists(), "alembic.ini not found at project root"
        cfg = configparser.ConfigParser()
        cfg.read(str(ini_path))
        assert cfg.get("alembic", "script_location") == "alembic"

    def test_env_py_exists_and_imports_base(self):
        env_path = ROOT / "alembic" / "env.py"
        assert env_path.exists(), "alembic/env.py not found"
        source = env_path.read_text()
        assert "from src.db.orm import Base" in source

    def test_initial_migration_exists(self):
        migration = ROOT / "alembic" / "versions" / "001_initial_schema.py"
        assert migration.exists(), "Initial migration file not found"


class TestInitialMigration:
    """Run the hand-written initial migration against a fresh in-memory SQLite."""

    @pytest.fixture()
    def _fresh_db(self, tmp_path):
        """Create a fresh temp SQLite, run upgrade, yield engine."""
        db_path = tmp_path / "test.db"
        self.engine = create_engine(f"sqlite:///{db_path}")
        # Import and run the migration manually
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "migration_001",
            str(ROOT / "alembic" / "versions" / "001_initial_schema.py"),
        )
        mod = importlib.util.module_from_spec(spec)

        # Alembic op needs a migration context — use direct SA instead
        # We'll use alembic's command API for a proper test
        from alembic.config import Config
        from alembic import command

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.upgrade(cfg, "head")
        self.cfg = cfg
        yield

    def test_upgrade_creates_all_six_tables(self, _fresh_db):
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        expected = {"companies", "contacts", "job_postings", "h1b_records", "scans", "outreach"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_downgrade_drops_all_tables(self, _fresh_db):
        from alembic import command

        command.downgrade(self.cfg, "base")
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert len(tables) == 0, f"Tables remain after downgrade: {tables}"

    def test_target_metadata_has_six_tables(self):
        from src.db.orm import Base

        table_names = set(Base.metadata.tables.keys())
        expected = {"companies", "contacts", "job_postings", "h1b_records", "scans", "outreach"}
        assert expected == table_names, f"Metadata mismatch: got {table_names}"
