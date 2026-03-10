"""Quality gates for outreach readiness and data completeness reporting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from src.config.enums import H1BStatus
from src.models.company import Company, CompletenessResult

# ---------------------------------------------------------------------------
# Portal staleness configuration
# ---------------------------------------------------------------------------

_DEFAULT_STALE_DAYS = 30
_PORTALS_YAML = Path(__file__).resolve().parents[2] / "config" / "portals.yaml"


def load_stale_thresholds(
    config_path: Path | str | None = None,
) -> dict[str, int]:
    """Load per-portal stale_after_days from portals.yaml.

    Returns a dict mapping portal key -> stale_after_days (int).
    If a portal doesn't specify one, uses the file-level default or 30.
    """
    path = Path(config_path) if config_path else _PORTALS_YAML
    if not path.exists():
        return {}

    with open(path) as fh:
        data = yaml.safe_load(fh) or {}

    file_default = data.get("default_stale_after_days", _DEFAULT_STALE_DAYS)
    portals: dict[str, Any] = data.get("portals", {})

    thresholds: dict[str, int] = {}
    for key, cfg in portals.items():
        thresholds[key] = int(cfg.get("stale_after_days", file_default))
    return thresholds


def is_stale(
    portal_key: str,
    last_updated: datetime,
    *,
    now: datetime | None = None,
    config_path: Path | str | None = None,
) -> bool:
    """Return True if the data from *portal_key* is older than its threshold."""
    thresholds = load_stale_thresholds(config_path)
    days = thresholds.get(portal_key, _DEFAULT_STALE_DAYS)
    ref = now or datetime.now()
    return (ref - last_updated) > timedelta(days=days)


# ---------------------------------------------------------------------------
# Outreach readiness gate
# ---------------------------------------------------------------------------


def is_outreach_ready(company: Company) -> bool:
    """Return True when a company passes the outreach quality gate.

    Conditions (ALL must be true):
    1. Completeness score >= 0.6
    2. h1b_status is not EXPLICIT_NO ("denied")
    3. hiring_manager is present (non-empty)
    """
    result: CompletenessResult = company.calculate_completeness()
    if result.score < 0.6:
        return False
    if company.h1b_status == H1BStatus.EXPLICIT_NO:
        return False
    return not (not company.hiring_manager or not company.hiring_manager.strip())


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------


@dataclass
class QualityReport:
    """Aggregate quality statistics for a list of companies."""

    total_companies: int = 0
    avg_completeness: float = 0.0
    bucket_0_25: int = 0    # 0-25% completeness
    bucket_25_50: int = 0   # 25-50%
    bucket_50_75: int = 0   # 50-75%
    bucket_75_100: int = 0  # 75-100%
    most_common_missing: list[tuple[str, int]] = field(default_factory=list)


def get_quality_report(companies: list[Company]) -> QualityReport:
    """Build a QualityReport summarising completeness across *companies*.

    Returns:
        QualityReport with avg completeness, bucket counts, and the top-N
        most commonly missing fields (sorted descending by frequency).
    """
    if not companies:
        return QualityReport()

    missing_counter: Counter[str] = Counter()
    scores: list[float] = []
    buckets = [0, 0, 0, 0]  # [0-25, 25-50, 50-75, 75-100]

    for company in companies:
        result = company.calculate_completeness()
        scores.append(result.score)
        missing_counter.update(result.missing_fields)

        pct = result.score * 100
        if pct < 25:
            buckets[0] += 1
        elif pct < 50:
            buckets[1] += 1
        elif pct < 75:
            buckets[2] += 1
        else:
            buckets[3] += 1

    avg = round(sum(scores) / len(scores), 4)

    return QualityReport(
        total_companies=len(companies),
        avg_completeness=avg,
        bucket_0_25=buckets[0],
        bucket_25_50=buckets[1],
        bucket_50_75=buckets[2],
        bucket_75_100=buckets[3],
        most_common_missing=missing_counter.most_common(),
    )
