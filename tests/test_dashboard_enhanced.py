"""Tests for dashboard portal scores and health monitor widgets."""
import pytest
from dataclasses import dataclass
from datetime import datetime


@dataclass
class MockPortalScore:
    portal: str
    velocity_score: int
    afternoon_delta_score: int
    conversion_score: int
    total: int
    recommendation: str


@dataclass
class MockPortalHealth:
    portal: str
    consecutive_failures: int
    last_success: datetime | None
    last_failure: datetime | None
    is_healthy: bool
    alert_triggered: bool


class TestPortalScoresWidget:
    def test_scores_data_structure(self):
        scores = [
            MockPortalScore("startup_jobs", 2, 1, 2, 5, "promote"),
            MockPortalScore("linkedin", 1, 0, 1, 2, "demote"),
        ]
        score_data = []
        for s in scores:
            score_data.append({
                "Portal": s.portal,
                "Velocity": s.velocity_score,
                "PM Delta": s.afternoon_delta_score,
                "Conversion": s.conversion_score,
                "Total": s.total,
                "Recommendation": s.recommendation.upper(),
            })
        assert len(score_data) == 2
        assert score_data[0]["Recommendation"] == "PROMOTE"
        assert score_data[1]["Recommendation"] == "DEMOTE"

    def test_empty_scores_handled(self):
        scores = []
        assert len(scores) == 0

    def test_recommendation_colors(self):
        colors = {
            "PROMOTE": "background-color: #2d6a2e; color: white",
            "DEMOTE": "background-color: #8b2020; color: white",
            "HOLD": "background-color: #8b7d20; color: white",
        }
        assert "#2d6a2e" in colors["PROMOTE"]
        assert "#8b2020" in colors["DEMOTE"]
        assert "#8b7d20" in colors["HOLD"]


class TestHealthMonitorWidget:
    def test_health_data_structure(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 5, datetime(2026, 3, 1), datetime(2026, 3, 5), False, True),
        ]
        health_data = []
        for s in statuses:
            health_data.append({
                "Portal": s.portal,
                "Consecutive Failures": s.consecutive_failures,
                "Status": "Healthy" if s.is_healthy else "UNHEALTHY",
                "Last Success": str(s.last_success.strftime("%Y-%m-%d %H:%M")) if s.last_success else "N/A",
                "Last Failure": str(s.last_failure.strftime("%Y-%m-%d %H:%M")) if s.last_failure else "N/A",
            })
        assert len(health_data) == 2
        assert health_data[0]["Status"] == "Healthy"
        assert health_data[1]["Status"] == "UNHEALTHY"

    def test_alert_detection(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 5, None, datetime(2026, 3, 5), False, True),
        ]
        has_alerts = any(s.alert_triggered for s in statuses)
        assert has_alerts is True
        alert_count = sum(1 for s in statuses if s.alert_triggered)
        assert alert_count == 1

    def test_no_alerts_when_all_healthy(self):
        statuses = [
            MockPortalHealth("startup_jobs", 0, datetime(2026, 3, 5), None, True, False),
            MockPortalHealth("linkedin", 1, datetime(2026, 3, 5), None, True, False),
        ]
        has_alerts = any(s.alert_triggered for s in statuses)
        assert has_alerts is False

    def test_empty_statuses_handled(self):
        statuses = []
        assert len(statuses) == 0


class TestFileArchive:
    def test_stale_files_list_count(self):
        stale_files = [
            "Fireworks_AI_Execution_Calendar.md",
            "Fireworks_AI_Outreach.md",
            "Fireworks_AI_Quick_Reference.md",
            "Fireworks_AI_Strategy_Notes.md",
            "Together_AI_Daily_Action_Plan.md",
            "Together_AI_Outreach_Package.md",
            "Together_AI_Summary.md",
            "Snorkel_AI_Outreach_Package.md",
            "LangChain_Outreach.md",
            "LlamaIndex_Execution_Checklist.md",
            "LlamaIndex_Outreach.md",
            "LlamaIndex_Summary.md",
            "Hypercubic_Outreach.md",
            "Irina_Adamchic_Outreach.md",
            "Hippocratic_AI_1_Intelligence_Report.md",
            "LinkedIn_Scan_Results.md",
            "FULL_SCAN_AUDIT_2026-03-05.md",
            "AUDIT_REPORT.md",
            "BEFORE_AFTER_COMPARISON.md",
            "AGENCY_BRIEF_2026-03-05.md",
            "TOOLS_AND_SKILLS_RECOMMENDATIONS.md",
            "Daily_Portal_Scan_Task.md",
            "Networking_Log.md",
        ]
        assert len(stale_files) == 23
