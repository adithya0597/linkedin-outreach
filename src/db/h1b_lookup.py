"""Known H1B status lookup and enrichment for Tier 1 companies."""

from __future__ import annotations

from loguru import logger

from src.db.orm import CompanyORM


# Verified via Frog Hire (primary), H1BGrader, MyVisaJobs (secondary)
KNOWN_H1B_STATUSES: dict[str, str] = {
    "Kumo AI": "Unknown",
    "LlamaIndex": "Confirmed",
    "Cursor": "Confirmed",
    "Hippocratic AI": "Confirmed",
    "LangChain": "Likely",
    "Norm AI": "Confirmed",
    "Spherecast": "Unknown",
    "Cinder": "Confirmed",
    "Augment Code": "Confirmed",
    "Pair Team": "Confirmed",
    "Snorkel AI": "Confirmed",
    "EvenUp": "Confirmed",
}


def apply_known_statuses(session) -> int:
    """Enrich companies with known H1B statuses from the lookup table.

    Queries CompanyORM where h1b_status is "Unknown", checks against
    KNOWN_H1B_STATUSES, and updates if the known status is not "Unknown".

    Args:
        session: Active SQLAlchemy session (must not be closed).

    Returns:
        Count of companies updated.
    """
    unknown_companies = (
        session.query(CompanyORM)
        .filter(CompanyORM.h1b_status == "Unknown")
        .all()
    )

    updated = 0
    for company in unknown_companies:
        # Case-insensitive lookup
        known_status = None
        for known_name, status in KNOWN_H1B_STATUSES.items():
            if company.name.lower() == known_name.lower():
                known_status = status
                break

        if known_status is not None and known_status != "Unknown":
            company.h1b_status = known_status
            company.h1b_source = "Known H1B Lookup (Frog Hire)"
            company.h1b_details = (
                f"{known_status} via Known H1B Lookup (Frog Hire verification)"
            )
            updated += 1
            logger.debug(
                f"H1B enriched: {company.name} -> {known_status}"
            )

    if updated > 0:
        session.commit()

    return updated
