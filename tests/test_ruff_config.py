"""Smoke tests for ruff configuration."""
import subprocess


def test_ruff_config_parses():
    """Verify ruff can parse the pyproject.toml config."""
    result = subprocess.run(
        ["ruff", "check", "--config", "pyproject.toml", "--show-settings"],
        capture_output=True,
        text=True,
    )
    # ruff exits 0 if config is valid
    assert result.returncode == 0 or "target-version" in result.stdout


def test_ruff_check_passes():
    """Verify ruff check passes on the codebase."""
    result = subprocess.run(
        ["ruff", "check", "src/", "tests/"],
        capture_output=True,
        text=True,
    )
    # Should pass (or only have ignored rules)
    assert result.returncode == 0, f"ruff check failed:\n{result.stdout}\n{result.stderr}"
