"""Auto-promotion pipeline — promotes/demotes portals in afternoon rescan based on scores."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from src.validators.portal_scorer import PortalScore, PortalScorer

HISTORY_PATH = Path(__file__).parent.parent.parent / "config" / "promotion_history.json"


class PortalAutoPromoter:
    """Evaluates portal scores and updates the afternoon rescan list."""

    def __init__(self, session: Session, config_path: str | None = None):
        self.session = session
        if config_path is None:
            config_path = str(
                Path(__file__).parent.parent.parent / "config" / "schedule.yaml"
            )
        self.config_path = config_path
        self.scorer = PortalScorer(session, config_path)
        self._last_evaluation: dict | None = None

    def _read_config(self) -> dict:
        with open(self.config_path) as f:
            return yaml.safe_load(f) or {}

    def _get_afternoon_portals(self, config: dict) -> list[str]:
        return (
            config.get("schedules", {})
            .get("afternoon_rescan", {})
            .get("portals", [])
        )

    def evaluate_promotions(self) -> dict:
        """Score all portals and classify into promotions/demotions/unchanged."""
        scores = self.scorer.score_all()
        promotions = [s.portal for s in scores if s.recommendation == "promote"]
        demotions = [s.portal for s in scores if s.recommendation == "demote"]
        unchanged = [s.portal for s in scores if s.recommendation == "hold"]

        result = {
            "promotions": promotions,
            "demotions": demotions,
            "unchanged": unchanged,
            "scores": scores,
        }
        self._last_evaluation = result
        logger.info(
            f"Evaluation: {len(promotions)} promote, {len(demotions)} demote, "
            f"{len(unchanged)} hold"
        )
        return result

    def apply_changes(self, dry_run: bool = False) -> dict:
        """Apply promotion/demotion changes to schedule.yaml."""
        if self._last_evaluation is None:
            self.evaluate_promotions()

        evaluation = self._last_evaluation
        config = self._read_config()
        current = self._get_afternoon_portals(config)

        added = []
        removed = []

        for portal in evaluation["promotions"]:
            if portal not in current:
                current.append(portal)
                added.append(portal)
                logger.info(f"Promoting {portal} to afternoon rescan")

        for portal in evaluation["demotions"]:
            if portal in current:
                current.remove(portal)
                removed.append(portal)
                logger.info(f"Demoting {portal} from afternoon rescan")

        if not dry_run and (added or removed):
            config["schedules"]["afternoon_rescan"]["portals"] = current
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Wrote updated schedule to {self.config_path}")
            for portal in added:
                self._log_change("promote", portal, "score-based promotion")
            for portal in removed:
                self._log_change("demote", portal, "score-based demotion")

        return {
            "added": added,
            "removed": removed,
            "current_list": list(current),
            "was_dry_run": dry_run,
        }

    def force_demote(self, portal_name: str) -> dict:
        """Force-demote a portal from the afternoon rescan list.

        Used by health monitor when a portal is unhealthy.
        Returns dict with removed (bool) and current_list.
        """
        config = self._read_config()
        current = self._get_afternoon_portals(config)

        removed = False
        if portal_name in current:
            current.remove(portal_name)
            config["schedules"]["afternoon_rescan"]["portals"] = current
            with open(self.config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            removed = True
            logger.info(f"Force-demoted '{portal_name}' from afternoon rescan (health)")
            self._log_change("force_demote", portal_name, "health monitor trigger")

        return {
            "removed": removed,
            "portal": portal_name,
            "current_list": list(current),
        }

    def _load_history(self) -> list[dict]:
        """Load promotion history from JSON file."""
        if HISTORY_PATH.exists():
            with open(HISTORY_PATH) as f:
                return json.load(f)
        return []

    def _log_change(self, action: str, portal: str, reason: str = "") -> None:
        """Append a change record to promotion_history.json."""
        history = self._load_history()
        history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "portal": portal,
            "reason": reason,
        })
        with open(HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)

    def get_change_history(self, limit: int = 50) -> list[dict]:
        """Return recent promotion/demotion history entries."""
        history = self._load_history()
        return history[-limit:]

    def get_change_log(self) -> str:
        """Return markdown summary of the last evaluation."""
        if self._last_evaluation is None:
            return "No evaluation has been run yet."

        scores: list[PortalScore] = self._last_evaluation["scores"]
        lines = ["# Portal Auto-Promotion Change Log\n"]

        promoted = [s for s in scores if s.recommendation == "promote"]
        demoted = [s for s in scores if s.recommendation == "demote"]
        held = [s for s in scores if s.recommendation == "hold"]

        if promoted:
            lines.append("## Promoted")
            for s in promoted:
                lines.append(
                    f"- **{s.portal}** (score {s.total}/6): "
                    f"velocity={s.velocity_score}, "
                    f"afternoon_delta={s.afternoon_delta_score}, "
                    f"conversion={s.conversion_score}"
                )
            lines.append("")

        if demoted:
            lines.append("## Demoted")
            for s in demoted:
                lines.append(
                    f"- **{s.portal}** (score {s.total}/6): "
                    f"velocity={s.velocity_score}, "
                    f"afternoon_delta={s.afternoon_delta_score}, "
                    f"conversion={s.conversion_score}"
                )
            lines.append("")

        if held:
            lines.append("## Unchanged")
            for s in held:
                lines.append(
                    f"- **{s.portal}** (score {s.total}/6): "
                    f"velocity={s.velocity_score}, "
                    f"afternoon_delta={s.afternoon_delta_score}, "
                    f"conversion={s.conversion_score}"
                )
            lines.append("")

        return "\n".join(lines)
