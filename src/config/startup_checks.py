"""Startup validation checks for API keys, config files, and system dependencies."""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "warning"  # "warning" or "error"

def validate_api_keys() -> list[CheckResult]:
    results = []
    for key, label in [
        ("NOTION_API_KEY", "Notion API"),
        ("NOTION_DATABASE_ID", "Notion Database ID"),
        ("APIFY_TOKEN", "Apify"),
    ]:
        val = os.environ.get(key)
        results.append(CheckResult(
            name=f"api_key_{key.lower()}",
            passed=bool(val),
            message=f"{label} key {'found' if val else 'missing'}",
            severity="error" if not val and key.startswith("NOTION") else "warning",
        ))
    return results

def validate_config_files() -> list[CheckResult]:
    results = []
    portals_path = Path("config/portals.yaml")
    if portals_path.exists():
        try:
            import yaml
            with open(portals_path) as f:
                yaml.safe_load(f)
            results.append(CheckResult("config_portals", True, "portals.yaml valid"))
        except Exception as e:
            results.append(CheckResult("config_portals", False, f"portals.yaml invalid: {e}", "error"))
    else:
        results.append(CheckResult("config_portals", False, "portals.yaml not found", "error"))
    return results

def validate_database() -> list[CheckResult]:
    db_path = Path("data/outreach.db")
    return [CheckResult(
        name="database",
        passed=db_path.exists(),
        message=f"Database {'found' if db_path.exists() else 'not found'} at {db_path}",
        severity="warning",
    )]

def validate_chrome() -> list[CheckResult]:
    chrome_path = Path("/Applications/Google Chrome.app")
    return [CheckResult(
        name="chrome",
        passed=chrome_path.exists(),
        message=f"Chrome {'found' if chrome_path.exists() else 'not found'}",
        severity="warning",
    )]

def run_all_checks() -> list[CheckResult]:
    results = []
    results.extend(validate_api_keys())
    results.extend(validate_config_files())
    results.extend(validate_database())
    results.extend(validate_chrome())

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    logger.info(f"Startup checks: {passed}/{total} passed")

    for r in results:
        if not r.passed:
            log_fn = logger.error if r.severity == "error" else logger.warning
            log_fn(f"Check '{r.name}' failed: {r.message}")

    return results
