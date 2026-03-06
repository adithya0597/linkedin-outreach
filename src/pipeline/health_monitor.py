"""Portal health monitor — tracks consecutive scan failures and alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.db.orm import ScanORM


@dataclass
class PortalHealth:
    """Health status for a single portal."""
    portal: str
    consecutive_failures: int
    last_success: datetime | None
    last_failure: datetime | None
    is_healthy: bool
    alert_triggered: bool


class HealthMonitor:
    """Monitors portal health by analyzing scan history."""

    def __init__(self, session: Session, failure_threshold: int = 3):
        self.session = session
        self.failure_threshold = failure_threshold

    def check_portal(self, portal: str) -> PortalHealth:
        """Check health status of a single portal by analyzing recent scans."""
        scans = self.session.query(ScanORM).filter(
            ScanORM.portal == portal,
        ).order_by(desc(ScanORM.started_at)).limit(20).all()

        if not scans:
            return PortalHealth(
                portal=portal,
                consecutive_failures=0,
                last_success=None,
                last_failure=None,
                is_healthy=True,
                alert_triggered=False,
            )

        consecutive_failures = 0
        for scan in scans:
            if scan.errors and scan.errors.strip():
                consecutive_failures += 1
            else:
                break

        last_success = None
        last_failure = None
        for scan in scans:
            if scan.errors and scan.errors.strip():
                if last_failure is None:
                    last_failure = scan.started_at
            else:
                if last_success is None:
                    last_success = scan.started_at
            if last_success and last_failure:
                break

        is_healthy = consecutive_failures < self.failure_threshold
        alert_triggered = consecutive_failures >= self.failure_threshold

        if alert_triggered:
            logger.warning(
                f"ALERT: Portal '{portal}' has {consecutive_failures} consecutive failures. "
                f"Last success: {last_success or 'never'}"
            )

        return PortalHealth(
            portal=portal,
            consecutive_failures=consecutive_failures,
            last_success=last_success,
            last_failure=last_failure,
            is_healthy=is_healthy,
            alert_triggered=alert_triggered,
        )

    def check_all(self) -> list[PortalHealth]:
        portals = self.session.query(ScanORM.portal).distinct().all()
        portal_names = [p[0] for p in portals]
        return [self.check_portal(name) for name in sorted(portal_names)]

    def get_alerts(self) -> list[PortalHealth]:
        return [h for h in self.check_all() if h.alert_triggered]

    def auto_demote_unhealthy(self) -> list[str]:
        """Return list of portals that should be demoted due to health issues."""
        alerts = self.get_alerts()
        return [a.portal for a in alerts]

    def get_actionable_alerts(self) -> list[dict]:
        """Return actionable alerts with severity and recommended actions.

        Returns list of dicts with: portal, alert_type, severity, recommended_action, details
        """
        alerts = []

        # Check for consecutive failures
        all_health = self.check_all()
        for h in all_health:
            if h.alert_triggered:
                alerts.append({
                    "portal": h.portal,
                    "alert_type": "consecutive_failures",
                    "severity": "critical" if h.consecutive_failures >= 5 else "warning",
                    "recommended_action": "force_demote" if h.consecutive_failures >= 5 else "investigate",
                    "details": f"{h.consecutive_failures} consecutive failures, last success: {h.last_success}",
                })

        # Check for zero yield
        zero_yield_portals = self.detect_zero_yield()
        for portal in zero_yield_portals:
            # Don't duplicate if already in failures
            if not any(a["portal"] == portal and a["alert_type"] == "consecutive_failures" for a in alerts):
                alerts.append({
                    "portal": portal,
                    "alert_type": "zero_yield",
                    "severity": "warning",
                    "recommended_action": "review_frequency",
                    "details": f"Zero new companies in last {self.failure_threshold} scans",
                })

        return alerts

    def detect_zero_yield(self, threshold: int = 5) -> list[str]:
        """Detect portals with zero new companies in the last N scans.

        Returns list of portal names that found 0 new companies in their
        last `threshold` scans.
        """
        portals = self.session.query(ScanORM.portal).distinct().all()
        zero_yield = []

        for (portal_name,) in portals:
            recent = (
                self.session.query(ScanORM)
                .filter(ScanORM.portal == portal_name)
                .order_by(desc(ScanORM.started_at))
                .limit(threshold)
                .all()
            )

            if len(recent) >= threshold:
                total_new = sum(s.new_companies for s in recent)
                if total_new == 0:
                    zero_yield.append(portal_name)
                    logger.warning(
                        f"Zero yield: '{portal_name}' found 0 new companies "
                        f"in last {threshold} scans"
                    )

        return zero_yield
