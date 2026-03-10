"""Tests for portal health monitor."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.orm import Base, ScanORM
from src.pipeline.health_monitor import HealthMonitor


@pytest.fixture
def health_session():
    """Session with scan records for portals at various health states."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    now = datetime.now()

    # Healthy portal "jobright" — 5 recent successful scans
    for i in range(5):
        session.add(ScanORM(
            portal="jobright",
            started_at=now - timedelta(hours=i * 6),
            companies_found=10,
            new_companies=3,
            errors="",
        ))

    # Failing portal "builtin" — 4 recent failures + 1 old success
    # Old success first (oldest)
    session.add(ScanORM(
        portal="builtin",
        started_at=now - timedelta(days=5),
        companies_found=5,
        new_companies=1,
        errors="",
    ))
    # Then 4 failures (newest)
    for i in range(4):
        session.add(ScanORM(
            portal="builtin",
            started_at=now - timedelta(hours=i * 6),
            companies_found=0,
            new_companies=0,
            errors=f"ConnectionError: timeout after {i+1} retries",
        ))

    # Intermittent portal "linkedin" — fail, success, fail (consecutive=1)
    session.add(ScanORM(
        portal="linkedin",
        started_at=now - timedelta(hours=18),
        companies_found=0,
        new_companies=0,
        errors="Rate limited",
    ))
    session.add(ScanORM(
        portal="linkedin",
        started_at=now - timedelta(hours=12),
        companies_found=8,
        new_companies=2,
        errors="",
    ))
    session.add(ScanORM(
        portal="linkedin",
        started_at=now - timedelta(hours=6),
        companies_found=0,
        new_companies=0,
        errors="Rate limited again",
    ))

    session.commit()
    yield session
    session.close()


class TestHealthMonitor:
    def test_healthy_portal_passes(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("jobright")
        assert result.consecutive_failures == 0
        assert result.is_healthy is True
        assert result.alert_triggered is False

    def test_failing_portal_triggers_alert(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("builtin")
        assert result.consecutive_failures == 4
        assert result.is_healthy is False
        assert result.alert_triggered is True

    def test_intermittent_doesnt_alert(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("linkedin")
        assert result.consecutive_failures == 1
        assert result.is_healthy is True
        assert result.alert_triggered is False

    def test_unknown_portal_assumed_healthy(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("nonexistent")
        assert result.is_healthy is True
        assert result.consecutive_failures == 0

    def test_custom_threshold(self, health_session):
        monitor = HealthMonitor(health_session, failure_threshold=5)
        result = monitor.check_portal("builtin")
        # 4 failures < threshold of 5, so still healthy
        assert result.is_healthy is True
        assert result.alert_triggered is False

    def test_last_success_tracked(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("builtin")
        assert result.last_success is not None
        # Last success should be ~5 days ago
        delta = datetime.now() - result.last_success
        assert delta.days >= 4  # Allow slight timing variance

    def test_last_failure_tracked(self, health_session):
        monitor = HealthMonitor(health_session)
        result = monitor.check_portal("builtin")
        assert result.last_failure is not None
        # Last failure should be recent (within hours)
        delta = datetime.now() - result.last_failure
        assert delta.total_seconds() < 86400  # Within 24 hours

    def test_get_alerts_returns_only_unhealthy(self, health_session):
        monitor = HealthMonitor(health_session)
        alerts = monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0].portal == "builtin"

    def test_check_all_returns_all_portals(self, health_session):
        monitor = HealthMonitor(health_session)
        all_health = monitor.check_all()
        assert len(all_health) == 3
        portal_names = [h.portal for h in all_health]
        assert "builtin" in portal_names
        assert "jobright" in portal_names
        assert "linkedin" in portal_names


class TestRegistryHealthIntegration:
    def test_get_healthy_scrapers_with_monitor(self, health_session):
        from src.scrapers.registry import PortalRegistry

        registry = PortalRegistry()

        # Register mock scrapers matching the portals in health_session
        for portal_name in ["jobright", "builtin", "linkedin"]:
            mock = MagicMock()
            mock.name = portal_name
            mock.is_healthy.return_value = True  # All report healthy via stub
            registry.register(portal_name, mock)

        monitor = HealthMonitor(health_session)
        healthy = registry.get_healthy_scrapers(health_monitor=monitor)

        # builtin has 4 consecutive failures (threshold=3), should be excluded
        healthy_names = [s.name for s in healthy]
        assert "builtin" not in healthy_names
        assert "jobright" in healthy_names
        assert "linkedin" in healthy_names
        assert len(healthy) == 2

    def test_get_healthy_scrapers_without_monitor(self):
        from src.scrapers.registry import PortalRegistry

        registry = PortalRegistry()

        healthy_mock = MagicMock()
        healthy_mock.name = "portal_a"
        healthy_mock.is_healthy.return_value = True
        registry.register("portal_a", healthy_mock)

        unhealthy_mock = MagicMock()
        unhealthy_mock.name = "portal_b"
        unhealthy_mock.is_healthy.return_value = False
        registry.register("portal_b", unhealthy_mock)

        # Without monitor, uses is_healthy() fallback
        healthy = registry.get_healthy_scrapers()
        assert len(healthy) == 1
        assert healthy[0].name == "portal_a"
