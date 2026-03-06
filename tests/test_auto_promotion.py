"""Tests for portal auto-promotion pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from src.pipeline.auto_promotion import PortalAutoPromoter
from src.validators.portal_scorer import PortalScore


def _make_schedule_yaml(tmp_path, portals=None):
    """Create a temporary schedule.yaml and return its path."""
    if portals is None:
        portals = ["wellfound", "yc", "linkedin", "jobright"]
    config = {
        "schedules": {
            "afternoon_rescan": {
                "portals": list(portals),
            }
        },
        "promotion_rules": {
            "promote_threshold": 4,
            "demote_threshold": 3,
            "review_window_weeks": 2,
        },
    }
    path = tmp_path / "schedule.yaml"
    with open(path, "w") as f:
        yaml.dump(config, f)
    return str(path)


def _score(portal, total, rec):
    """Helper to build a PortalScore with minimal fields."""
    return PortalScore(
        portal=portal,
        velocity_score=min(total, 2),
        afternoon_delta_score=min(max(total - 2, 0), 2),
        conversion_score=min(max(total - 4, 0), 2),
        total=total,
        recommendation=rec,
    )


class TestAutoPromotion:
    def test_promote_adds_portal(self, tmp_path):
        """Promoting a portal adds it to the afternoon rescan list."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "yc"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": ["hiring_cafe"],
                "demotions": [],
                "unchanged": ["wellfound", "yc"],
                "scores": [
                    _score("hiring_cafe", 5, "promote"),
                    _score("wellfound", 3, "hold"),
                    _score("yc", 3, "hold"),
                ],
            }

        result = promoter.apply_changes()
        assert "hiring_cafe" in result["added"]
        assert "hiring_cafe" in result["current_list"]
        assert result["was_dry_run"] is False

        # Verify yaml was written
        with open(config_path) as f:
            written = yaml.safe_load(f)
        assert "hiring_cafe" in written["schedules"]["afternoon_rescan"]["portals"]

    def test_demote_removes_portal(self, tmp_path):
        """Demoting a portal removes it from the afternoon rescan list."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "builtin", "yc"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": [],
                "demotions": ["builtin"],
                "unchanged": ["wellfound", "yc"],
                "scores": [
                    _score("builtin", 1, "demote"),
                    _score("wellfound", 3, "hold"),
                    _score("yc", 3, "hold"),
                ],
            }

        result = promoter.apply_changes()
        assert "builtin" in result["removed"]
        assert "builtin" not in result["current_list"]

        with open(config_path) as f:
            written = yaml.safe_load(f)
        assert "builtin" not in written["schedules"]["afternoon_rescan"]["portals"]

    def test_hold_keeps_list_unchanged(self, tmp_path):
        """Hold recommendation keeps the portal list unchanged."""
        original_portals = ["wellfound", "yc", "linkedin"]
        config_path = _make_schedule_yaml(tmp_path, original_portals)

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": [],
                "demotions": [],
                "unchanged": ["wellfound", "yc", "linkedin"],
                "scores": [
                    _score("wellfound", 3, "hold"),
                    _score("yc", 3, "hold"),
                    _score("linkedin", 3, "hold"),
                ],
            }

        result = promoter.apply_changes()
        assert result["added"] == []
        assert result["removed"] == []
        assert sorted(result["current_list"]) == sorted(original_portals)

    def test_promote_no_duplicate(self, tmp_path):
        """Promoting a portal already in the list does not duplicate it."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "jobright"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": ["jobright"],
                "demotions": [],
                "unchanged": ["wellfound"],
                "scores": [
                    _score("jobright", 5, "promote"),
                    _score("wellfound", 3, "hold"),
                ],
            }

        result = promoter.apply_changes()
        assert result["added"] == []  # already in list, so no addition
        assert result["current_list"].count("jobright") == 1

    def test_demote_not_in_list_no_error(self, tmp_path):
        """Demoting a portal not in the list does not raise an error."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "yc"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": [],
                "demotions": ["nonexistent_portal"],
                "unchanged": ["wellfound", "yc"],
                "scores": [
                    _score("nonexistent_portal", 1, "demote"),
                    _score("wellfound", 3, "hold"),
                    _score("yc", 3, "hold"),
                ],
            }

        result = promoter.apply_changes()
        assert result["removed"] == []  # wasn't in list, nothing removed
        assert "nonexistent_portal" not in result["current_list"]

    def test_dry_run_no_write(self, tmp_path):
        """dry_run=True returns changes without writing yaml."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "yc"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": ["hiring_cafe"],
                "demotions": [],
                "unchanged": ["wellfound", "yc"],
                "scores": [
                    _score("hiring_cafe", 5, "promote"),
                    _score("wellfound", 3, "hold"),
                    _score("yc", 3, "hold"),
                ],
            }

        result = promoter.apply_changes(dry_run=True)
        assert result["was_dry_run"] is True
        assert "hiring_cafe" in result["added"]

        # File should NOT have been modified
        with open(config_path) as f:
            written = yaml.safe_load(f)
        assert "hiring_cafe" not in written["schedules"]["afternoon_rescan"]["portals"]

    def test_change_log_includes_breakdown(self, tmp_path):
        """change_log includes score breakdown for affected portals."""
        config_path = _make_schedule_yaml(tmp_path)

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": ["hiring_cafe"],
                "demotions": ["builtin"],
                "unchanged": [],
                "scores": [
                    _score("hiring_cafe", 5, "promote"),
                    _score("builtin", 1, "demote"),
                ],
            }

        log = promoter.get_change_log()
        assert "hiring_cafe" in log
        assert "builtin" in log
        assert "velocity=" in log
        assert "afternoon_delta=" in log
        assert "conversion=" in log
        assert "Promoted" in log
        assert "Demoted" in log

    def test_empty_scores_no_changes(self, tmp_path):
        """When score_all returns empty, no changes are made."""
        config_path = _make_schedule_yaml(tmp_path, ["wellfound", "yc"])

        with patch.object(
            PortalAutoPromoter, "__init__", lambda self, *a, **kw: None
        ):
            promoter = PortalAutoPromoter.__new__(PortalAutoPromoter)
            promoter.config_path = config_path
            promoter.scorer = None
            promoter._last_evaluation = {
                "promotions": [],
                "demotions": [],
                "unchanged": [],
                "scores": [],
            }

        result = promoter.apply_changes()
        assert result["added"] == []
        assert result["removed"] == []
        assert sorted(result["current_list"]) == sorted(["wellfound", "yc"])
