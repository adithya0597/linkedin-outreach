"""Tests for Portal Intelligence: change history, actionable alerts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, ScanORM
from src.pipeline.auto_promotion import HISTORY_PATH, PortalAutoPromoter
from src.pipeline.health_monitor import HealthMonitor


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture()
def temp_history(tmp_path):
    """Provide a temporary promotion_history.json path."""
    return tmp_path / "promotion_history.json"


def _seed_scans(session, portal, count=5, with_errors=False):
    """Seed scan records for a portal."""
    for i in range(count):
        scan = ScanORM(
            portal=portal,
            started_at=datetime(2026, 3, 5, 10 + i, 0, 0),
            companies_found=0 if with_errors else 3,
            new_companies=0,
            errors="Connection timeout" if with_errors else "",
        )
        session.add(scan)
    session.commit()


def test_change_history_starts_empty(temp_history):
    """get_change_history returns empty list when no history file exists."""
    with patch("src.pipeline.auto_promotion.HISTORY_PATH", temp_history):
        promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
        history = promoter._load_history()
        assert history == []


def test_log_change_persists(temp_history):
    """_log_change writes to the history file."""
    with patch("src.pipeline.auto_promotion.HISTORY_PATH", temp_history):
        promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
        promoter._log_change("promote", "jobright.ai", "score-based promotion")

        assert temp_history.exists()
        with open(temp_history) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["action"] == "promote"
        assert data[0]["portal"] == "jobright.ai"
        assert data[0]["reason"] == "score-based promotion"
        assert "timestamp" in data[0]


def test_log_change_appends(temp_history):
    """Multiple _log_change calls append entries, not overwrite."""
    with patch("src.pipeline.auto_promotion.HISTORY_PATH", temp_history):
        promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
        promoter._log_change("promote", "portal_a", "first")
        promoter._log_change("demote", "portal_b", "second")

        with open(temp_history) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["action"] == "promote"
        assert data[1]["action"] == "demote"


def test_get_change_history_limit(temp_history):
    """get_change_history respects the limit parameter."""
    with patch("src.pipeline.auto_promotion.HISTORY_PATH", temp_history):
        promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
        for i in range(10):
            promoter._log_change("promote", f"portal_{i}", "test")

        result = promoter.get_change_history(limit=3)
        assert len(result) == 3
        # Should return the LAST 3 entries
        assert result[0]["portal"] == "portal_7"
        assert result[1]["portal"] == "portal_8"
        assert result[2]["portal"] == "portal_9"


def test_force_demote_logs_history(temp_history, tmp_path):
    """force_demote should log to promotion_history.json."""
    config_path = tmp_path / "schedule.yaml"
    config = {
        "schedules": {
            "afternoon_rescan": {
                "portals": ["jobright.ai", "hiring.cafe"]
            }
        },
        "promotion_rules": {
            "promote_threshold": 4,
            "demote_threshold": 3,
            "review_window_weeks": 2,
        },
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    with patch("src.pipeline.auto_promotion.HISTORY_PATH", temp_history):
        session_mock = MagicMock()
        promoter = PortalAutoPromoter(session_mock, config_path=str(config_path))
        promoter.force_demote("jobright.ai")

        with open(temp_history) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["action"] == "force_demote"
        assert data[0]["portal"] == "jobright.ai"
        assert data[0]["reason"] == "health monitor trigger"


def test_actionable_alerts_consecutive_failures(session):
    """Portals with consecutive failures produce actionable alerts."""
    _seed_scans(session, "badportal.com", count=5, with_errors=True)

    monitor = HealthMonitor(session, failure_threshold=3)
    alerts = monitor.get_actionable_alerts()

    assert len(alerts) >= 1
    alert = next(a for a in alerts if a["portal"] == "badportal.com")
    assert alert["alert_type"] == "consecutive_failures"
    assert alert["severity"] in ("warning", "critical")
    assert alert["recommended_action"] in ("investigate", "force_demote")


def test_actionable_alerts_zero_yield(session):
    """Portals with zero yield produce zero_yield alerts."""
    _seed_scans(session, "dryportal.com", count=5, with_errors=False)  # 0 new_companies

    monitor = HealthMonitor(session, failure_threshold=3)
    alerts = monitor.get_actionable_alerts()

    zero_alerts = [a for a in alerts if a["portal"] == "dryportal.com" and a["alert_type"] == "zero_yield"]
    assert len(zero_alerts) == 1
    assert zero_alerts[0]["severity"] == "warning"
    assert zero_alerts[0]["recommended_action"] == "review_frequency"


def test_actionable_alerts_empty_db(session):
    """Empty database produces no alerts."""
    monitor = HealthMonitor(session)
    alerts = monitor.get_actionable_alerts()
    assert alerts == []
