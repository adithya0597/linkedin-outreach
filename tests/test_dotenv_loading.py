"""Tests for python-dotenv integration."""

import os
from pathlib import Path

from dotenv import load_dotenv


def test_cli_has_load_dotenv_import():
    """Verify src/cli/main.py contains dotenv import and call."""
    cli_path = Path(__file__).resolve().parents[1] / "src" / "cli" / "main.py"
    source = cli_path.read_text()
    assert "from dotenv import load_dotenv" in source
    assert "load_dotenv()" in source


def test_env_var_loaded_from_dotenv(tmp_path):
    """Verify load_dotenv reads variables from a .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_DOTENV_VAR=hello\n")
    # Remove the var if it already exists
    os.environ.pop("TEST_DOTENV_VAR", None)
    load_dotenv(env_file)
    assert os.getenv("TEST_DOTENV_VAR") == "hello"
    # Cleanup
    os.environ.pop("TEST_DOTENV_VAR", None)


def test_dashboard_loads_dotenv():
    """Verify src/dashboard/app.py contains dotenv import and call."""
    dash_path = Path(__file__).resolve().parents[1] / "src" / "dashboard" / "app.py"
    source = dash_path.read_text()
    assert "from dotenv import load_dotenv" in source
    assert "load_dotenv()" in source
