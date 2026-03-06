"""Parse Startup_Target_List.md and seed the SQLite database."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config.enums import (
    CompanyStage,
    FundingStage,
    H1BStatus,
    SourcePortal,
    Tier,
    ValidationResult,
)
from src.db.database import get_engine, get_session, init_db
from src.db.orm import CompanyORM


def parse_funding_stage(text: str) -> FundingStage:
    """Extract funding stage from text like 'Series C — $135M'."""
    text_lower = text.lower()
    for stage in [
        ("series f", FundingStage.SERIES_F),
        ("series e", FundingStage.SERIES_E),
        ("series d", FundingStage.SERIES_D),
        ("series c", FundingStage.SERIES_C),
        ("series b", FundingStage.SERIES_B),
        ("series a", FundingStage.SERIES_A),
        ("seed", FundingStage.SEED),
        ("pre-seed", FundingStage.PRE_SEED),
        ("yc", FundingStage.SEED),
    ]:
        if stage[0] in text_lower:
            return stage[1]
    return FundingStage.UNKNOWN


def parse_employees(text: str) -> tuple[int | None, str]:
    """Extract employee count from text like '~200-300' or '51-200'."""
    # Try range first: ~200-300, 100-200, 251-500
    range_match = re.search(r"~?(\d+)\s*[-–]\s*(\d+)", text)
    if range_match:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        return (low + high) // 2, f"{low}-{high}"
    # Try single number: <10, ~15
    single_match = re.search(r"[<~]?\s*(\d+)", text)
    if single_match:
        return int(single_match.group(1)), text.strip()
    return None, text.strip()


def parse_h1b_status(text: str) -> H1BStatus:
    """Extract H1B status from text."""
    text_lower = text.lower()
    if "confirmed" in text_lower or "✅" in text:
        return H1BStatus.CONFIRMED
    if "likely" in text_lower:
        return H1BStatus.LIKELY
    if "explicit no" in text_lower or "does not sponsor" in text_lower:
        return H1BStatus.EXPLICIT_NO
    if "n/a" in text_lower:
        return H1BStatus.NOT_APPLICABLE
    return H1BStatus.UNKNOWN


def parse_source_portal(text: str) -> SourcePortal:
    """Map source text to SourcePortal enum."""
    text_lower = text.lower()
    mapping = {
        "linkedin": SourcePortal.LINKEDIN,
        "wellfound": SourcePortal.WELLFOUND,
        "yc": SourcePortal.YC,
        "work at a startup": SourcePortal.YC,
        "startup.jobs": SourcePortal.STARTUP_JOBS,
        "hiring cafe": SourcePortal.HIRING_CAFE,
        "top startups": SourcePortal.TOP_STARTUPS,
        "topstartups": SourcePortal.TOP_STARTUPS,
        "jobright": SourcePortal.JOBRIGHT,
        "trueup": SourcePortal.TRUEUP,
        "ai jobs": SourcePortal.AI_JOBS,
        "built in": SourcePortal.BUILT_IN,
        "frog hire": SourcePortal.FROG_HIRE,
        "web search": SourcePortal.WEB_SEARCH,
    }
    for key, val in mapping.items():
        if key in text_lower:
            return val
    return SourcePortal.MANUAL


def parse_tier(section_header: str, entry_num: int) -> Tier:
    """Determine tier from the markdown section header."""
    if "TIER 1" in section_header:
        return Tier.TIER_1
    if "TIER 2" in section_header:
        return Tier.TIER_2
    if "TIER 3" in section_header:
        return Tier.TIER_3
    if "TIER 4" in section_header or "PORTAL-SOURCED" in section_header:
        return Tier.TIER_4
    if "TIER 5" in section_header or "RESCAN" in section_header:
        return Tier.TIER_5
    return Tier.TIER_5


def parse_startup_target_list(filepath: str) -> list[dict]:
    """Parse the Startup_Target_List.md markdown into structured company records."""
    path = Path(filepath)
    content = path.read_text(encoding="utf-8")
    companies = []
    current_tier_section = ""
    current_entry: dict | None = None
    entry_num = 0

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Track tier section headers
        if line.startswith("## TIER") or "PORTAL-SOURCED" in line or "RESCAN" in line:
            current_tier_section = line
            i += 1
            continue

        # Detect company entry: ### N. Company Name or #### N. Company Name
        entry_match = re.match(r"^#{2,4}\s+(\d+)\.\s+(.+?)(?:\s+[⭐❌🔴].*)?$", line)
        if entry_match:
            # Save previous entry
            if current_entry:
                companies.append(current_entry)

            entry_num = int(entry_match.group(1))
            raw_name = entry_match.group(2).strip()
            # Clean strikethrough
            name = re.sub(r"~~(.+?)~~", r"\1", raw_name).strip()
            is_disqualified = "~~" in raw_name or "❌" in line or "DISQUALIFIED" in line

            current_entry = {
                "entry_num": entry_num,
                "name": name,
                "tier_section": current_tier_section,
                "is_disqualified": is_disqualified,
                "description": "",
                "hq_location": "",
                "employees": None,
                "employees_range": "",
                "funding_stage": "Unknown",
                "funding_amount": "",
                "source_portal": "Manual",
                "h1b_status": "Unknown",
                "h1b_details": "",
                "role": "",
                "salary_range": "",
                "why_fit": "",
                "best_stats": "",
                "action": "",
                "hiring_manager": "",
                "notes": "",
                "fit_score": None,
            }
            i += 1
            continue

        # Parse fields within an entry
        if current_entry and line.startswith("- **"):
            # Handle both "**Field:** value" and "**Field**: value" patterns
            field_match = re.match(
                r"- \*\*(.+?)(?::\*\*|\*\*\s*[:：])\s*(.*)", line
            )
            if field_match:
                field_name = field_match.group(1).lower().strip()
                field_value = field_match.group(2).strip()

                if field_name in ("what", "what it does"):
                    current_entry["description"] = field_value
                elif field_name == "hq":
                    current_entry["hq_location"] = field_value
                elif field_name == "employees":
                    emp, emp_range = parse_employees(field_value)
                    current_entry["employees"] = emp
                    current_entry["employees_range"] = emp_range
                elif field_name == "funding":
                    current_entry["funding_stage"] = parse_funding_stage(field_value).value
                    current_entry["funding_amount"] = field_value
                elif field_name == "source":
                    current_entry["source_portal"] = parse_source_portal(field_value).value
                elif field_name == "role":
                    current_entry["role"] = field_value
                elif field_name in ("salary", "salary range"):
                    current_entry["salary_range"] = field_value
                elif field_name.startswith("why fit"):
                    current_entry["why_fit"] = field_value
                elif field_name.startswith("best stats"):
                    current_entry["best_stats"] = field_value
                elif field_name == "action":
                    current_entry["action"] = field_value
                elif field_name in ("h1b", "h1b status"):
                    current_entry["h1b_status"] = parse_h1b_status(field_value).value
                    current_entry["h1b_details"] = field_value
                elif "linkedin contact" in field_name or "contact" in field_name:
                    current_entry["hiring_manager"] = field_value
                elif field_name == "fit score":
                    score_match = re.search(r"(\d+)", field_value)
                    if score_match:
                        current_entry["fit_score"] = float(score_match.group(1))
                elif field_name == "location":
                    current_entry["hq_location"] = field_value

        i += 1

    # Don't forget the last entry
    if current_entry:
        companies.append(current_entry)

    return companies


# Known data quality issues to flag during migration
DISQUALIFIED_COMPANIES = {
    "Harvey AI": "Series F $8B — exceeds Series C funding criteria",
    "Perplexity AI": "Series D $20B — exceeds Series C funding criteria",
    "Runway": "Series E $5.3B — exceeds Series C funding criteria",
}

BORDERLINE_COMPANIES = {
    "Cursor": "Series D $2.3B — borderline, needs manual review",
}

TIER_MISMATCHES = {
    "Cohere Health": "Should be Tier 1 (healthcare AI, strong fit)",
    "Truveta": "Should be Tier 1 (healthcare LLM, strong fit)",
    "Virio": "Should be Tier 2 (H1B confirmed, founding role)",
    "Komodo Health": "Should be Tier 2 (may exceed 1000 employees)",
}


def seed_database(
    target_list_path: str = "Startup_Target_List.md",
    db_path: str = "data/outreach.db",
) -> dict:
    """Parse markdown and seed SQLite. Returns audit report."""
    engine = get_engine(db_path)
    init_db(engine)
    session = get_session(engine)

    parsed = parse_startup_target_list(target_list_path)
    logger.info(f"Parsed {len(parsed)} companies from {target_list_path}")

    audit = {
        "total_parsed": len(parsed),
        "inserted": 0,
        "disqualified": [],
        "borderline": [],
        "tier_mismatches": [],
        "skeleton_records": [],
        "score_anomalies": [],
    }

    for entry in parsed:
        name = entry["name"]
        tier = parse_tier(entry["tier_section"], entry["entry_num"])

        # Check for known disqualifications
        is_disqualified = entry.get("is_disqualified", False)
        disqualification_reason = ""
        needs_review = False

        if name in DISQUALIFIED_COMPANIES:
            is_disqualified = True
            disqualification_reason = DISQUALIFIED_COMPANIES[name]
            audit["disqualified"].append(f"{name}: {disqualification_reason}")

        if name in BORDERLINE_COMPANIES:
            needs_review = True
            audit["borderline"].append(f"{name}: {BORDERLINE_COMPANIES[name]}")

        if name in TIER_MISMATCHES:
            audit["tier_mismatches"].append(f"{name}: {TIER_MISMATCHES[name]}")

        # Check for skeleton records
        completeness_fields = [
            entry.get("description"),
            entry.get("hq_location"),
            entry.get("employees") or entry.get("employees_range"),
            entry.get("funding_stage") != "Unknown",
            entry.get("role"),
        ]
        filled = sum(1 for f in completeness_fields if f)
        completeness = round(filled / len(completeness_fields) * 100, 1)
        if completeness < 40:
            audit["skeleton_records"].append(f"{name}: {completeness}% complete")
            needs_review = True

        company = CompanyORM(
            name=name,
            description=entry.get("description", ""),
            hq_location=entry.get("hq_location", ""),
            employees=entry.get("employees"),
            employees_range=entry.get("employees_range", ""),
            funding_stage=entry.get("funding_stage", "Unknown"),
            funding_amount=entry.get("funding_amount", ""),
            tier=tier.value,
            source_portal=entry.get("source_portal", "Manual"),
            h1b_status=entry.get("h1b_status", "Unknown"),
            h1b_details=entry.get("h1b_details", ""),
            fit_score=entry.get("fit_score"),
            role=entry.get("role", ""),
            salary_range=entry.get("salary_range", ""),
            why_fit=entry.get("why_fit", ""),
            best_stats=entry.get("best_stats", ""),
            action=entry.get("action", ""),
            hiring_manager=entry.get("hiring_manager", ""),
            notes=entry.get("notes", ""),
            is_disqualified=is_disqualified,
            disqualification_reason=disqualification_reason,
            needs_review=needs_review,
            data_completeness=completeness,
            stage=CompanyStage.DISQUALIFIED.value if is_disqualified else CompanyStage.TO_APPLY.value,
            is_ai_native=True,  # All entries were pre-filtered for AI-native
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(company)
        audit["inserted"] += 1

    session.commit()
    session.close()

    logger.info(f"Seeded {audit['inserted']} companies into {db_path}")
    logger.info(f"Disqualified: {len(audit['disqualified'])}")
    logger.info(f"Borderline: {len(audit['borderline'])}")
    logger.info(f"Skeleton records: {len(audit['skeleton_records'])}")
    logger.info(f"Tier mismatches: {len(audit['tier_mismatches'])}")

    return audit


if __name__ == "__main__":
    audit = seed_database()
    print("\n=== MIGRATION AUDIT REPORT ===")
    print(f"Total parsed: {audit['total_parsed']}")
    print(f"Inserted: {audit['inserted']}")
    print(f"\nDisqualified ({len(audit['disqualified'])}):")
    for d in audit["disqualified"]:
        print(f"  ❌ {d}")
    print(f"\nBorderline ({len(audit['borderline'])}):")
    for b in audit["borderline"]:
        print(f"  ⚠️ {b}")
    print(f"\nSkeleton records ({len(audit['skeleton_records'])}):")
    for s in audit["skeleton_records"]:
        print(f"  📋 {s}")
    print(f"\nTier mismatches ({len(audit['tier_mismatches'])}):")
    for t in audit["tier_mismatches"]:
        print(f"  🔄 {t}")
