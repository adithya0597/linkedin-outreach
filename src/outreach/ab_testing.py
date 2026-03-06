from __future__ import annotations

import json
import random
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import OutreachORM

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ab_experiments.json"


class ABTestManager:
    """Manages A/B test experiments for outreach templates."""

    def __init__(self, session: Session, config_path: str | Path | None = None) -> None:
        self.session = session
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._ensure_config()

    def _ensure_config(self) -> None:
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_config({"experiments": {}})

    def _read_config(self) -> dict:
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _write_config(self, data: dict) -> None:
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=2)

    def create_experiment(
        self, name: str, variants: list[str], allocation: str = "round_robin"
    ) -> dict:
        if allocation not in ("round_robin", "random"):
            raise ValueError(f"Invalid allocation strategy: {allocation}")

        config = self._read_config()

        experiment_id = str(uuid.uuid4())[:8]
        experiment = {
            "experiment_id": experiment_id,
            "name": name,
            "variants": variants,
            "allocation": allocation,
            "assignments": {},
            "round_robin_index": 0,
            "created_at": datetime.now().isoformat(),
            "status": "active",
        }
        config["experiments"][name] = experiment
        self._write_config(config)

        logger.info(f"Created experiment '{name}' with variants {variants}")
        return {
            "experiment_id": experiment_id,
            "name": name,
            "variants": variants,
            "created_at": experiment["created_at"],
        }

    def assign_variant(self, experiment_name: str, company_name: str) -> str:
        config = self._read_config()

        if experiment_name not in config["experiments"]:
            raise KeyError(f"Experiment '{experiment_name}' not found")

        experiment = config["experiments"][experiment_name]
        assignments = experiment["assignments"]

        # Return existing assignment for duplicate company
        if company_name in assignments:
            logger.debug(f"'{company_name}' already assigned to '{assignments[company_name]}'")
            return assignments[company_name]

        variants = experiment["variants"]
        allocation = experiment["allocation"]

        if allocation == "round_robin":
            idx = experiment["round_robin_index"]
            variant = variants[idx % len(variants)]
            experiment["round_robin_index"] = idx + 1
        else:  # random
            variant = random.choice(variants)

        assignments[company_name] = variant
        self._write_config(config)

        logger.info(f"Assigned '{company_name}' to variant '{variant}' in '{experiment_name}'")
        return variant

    def get_active_experiment(self) -> dict | None:
        """Return the first active experiment, or None if no active experiments."""
        config = self._read_config()
        for name, exp in config["experiments"].items():
            if exp.get("status") == "active":
                return {
                    "experiment_id": exp["experiment_id"],
                    "name": exp["name"],
                    "variants": exp["variants"],
                    "allocation": exp["allocation"],
                    "status": exp["status"],
                }
        return None

    def get_experiment_results(self, experiment_name: str) -> dict:
        config = self._read_config()

        if experiment_name not in config["experiments"]:
            raise KeyError(f"Experiment '{experiment_name}' not found")

        experiment = config["experiments"][experiment_name]
        variants = experiment["variants"]
        assignments = experiment["assignments"]

        variant_results = []
        for variant in variants:
            companies = [c for c, v in assignments.items() if v == variant]
            assigned_count = len(companies)

            sent_count = 0
            responded_count = 0
            for company in companies:
                records = (
                    self.session.query(OutreachORM)
                    .filter(
                        OutreachORM.company_name == company,
                        OutreachORM.template_type == variant,
                    )
                    .all()
                )
                for record in records:
                    if record.stage in ("Sent", "Responded"):
                        sent_count += 1
                    if record.stage == "Responded":
                        responded_count += 1

            response_rate = (responded_count / sent_count * 100) if sent_count > 0 else 0.0

            variant_results.append({
                "template": variant,
                "assigned": assigned_count,
                "sent": sent_count,
                "responded": responded_count,
                "response_rate": round(response_rate, 2),
            })

        # Determine winner
        winner = None
        is_significant = False
        if variant_results:
            best = max(variant_results, key=lambda v: v["response_rate"])
            if best["response_rate"] > 0:
                winner = best["template"]

            # Significance: min 10 sends per variant and rate difference > 5%
            rates = [v["response_rate"] for v in variant_results]
            sends = [v["sent"] for v in variant_results]
            if all(s >= 10 for s in sends) and len(rates) >= 2:
                rate_diff = max(rates) - min(rates)
                if rate_diff > 5:
                    is_significant = True

        return {
            "variants": variant_results,
            "winner": winner,
            "is_significant": is_significant,
        }

    def list_experiments(self) -> list[dict]:
        config = self._read_config()
        result = []
        for name, exp in config["experiments"].items():
            result.append({
                "experiment_id": exp["experiment_id"],
                "name": exp["name"],
                "variants": exp["variants"],
                "allocation": exp["allocation"],
                "status": exp["status"],
                "created_at": exp["created_at"],
                "total_assignments": len(exp["assignments"]),
            })
        return result
