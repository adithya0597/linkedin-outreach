"""LinkedIn contact research assistant — generates search URLs, records contacts, ranks them."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus

from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM


# Priority ranking for contact titles (lower = higher priority)
TITLE_PRIORITY: dict[str, int] = {
    "CTO": 1,
    "Chief Technology Officer": 1,
    "VP Engineering": 1,
    "VP of Engineering": 1,
    "Co-Founder": 1,
    "VP Product": 1,
    "VP of Product": 1,
    "Head of AI": 1,
    "Head of Engineering": 2,
    "Director of Engineering": 2,
    "Staff Engineer": 2,
    "Principal Engineer": 2,
    "Director of AI": 2,
    "Engineering Manager": 3,
    "Senior Recruiter": 3,
    "Technical Recruiter": 3,
    "Lead Recruiter": 3,
    "ML Engineering Manager": 3,
    "Talent Acquisition": 4,
    "People Operations": 4,
    "Recruiter": 5,
    "HR Manager": 5,
}

# Titles to search for, in priority order
SEARCH_TITLES = [
    "CTO",
    "VP Engineering",
    "Head of Engineering",
    "Engineering Manager",
    "Senior Recruiter",
    "Recruiter",
    "Co-Founder",
    "Head of AI",
    "Staff Engineer",
]


class ContactResearcher:
    """Semi-automated LinkedIn contact research assistant."""

    def __init__(self, session: Session):
        self.session = session

    def _build_linkedin_search_url(self, company: str, title: str) -> str:
        """Build a LinkedIn People search URL."""
        query = f"{title} {company}"
        return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(query)}"

    def _get_company(self, company_name: str) -> CompanyORM | None:
        """Find company by name (case-insensitive)."""
        return self.session.query(CompanyORM).filter(
            CompanyORM.name.ilike(company_name.strip())
        ).first()

    def find_hiring_contacts(self, company_name: str) -> list[dict]:
        """Generate LinkedIn search URLs for hiring contacts at a company.

        Returns list of dicts with: title, priority, search_url, company
        Sorted by priority (lowest number = highest priority).
        """
        results = []
        for title in SEARCH_TITLES:
            priority = TITLE_PRIORITY.get(title, 99)
            url = self._build_linkedin_search_url(company_name, title)
            results.append({
                "title": title,
                "priority": priority,
                "search_url": url,
                "company": company_name,
            })
        results.sort(key=lambda x: x["priority"])
        logger.info(f"Generated {len(results)} search URLs for {company_name}")
        return results

    def record_contact(self, company_name: str, contact_data: dict) -> ContactORM:
        """Record a contact and link to CompanyORM if found.

        contact_data keys: name (required), title, linkedin_url,
        linkedin_degree, is_open_profile, followers, location, recent_posts,
        email (optional — saved to ContactORM.email if provided)

        Dedup: if a contact with the same name AND company already exists,
        update the existing record instead of creating a duplicate.
        """
        company = self._get_company(company_name)
        title = contact_data.get("title", "")
        priority = self._get_title_priority(title)
        score = self._calculate_contact_score(priority, contact_data)
        email = contact_data.get("email", "")

        # Dedup: check for existing contact with same name + company
        existing = self.session.query(ContactORM).filter(
            ContactORM.name == contact_data["name"],
            ContactORM.company_name == company_name,
        ).first()

        if existing:
            # Update existing record
            existing.title = title
            existing.linkedin_url = contact_data.get("linkedin_url", existing.linkedin_url)
            existing.linkedin_degree = contact_data.get("linkedin_degree", existing.linkedin_degree)
            existing.is_open_profile = contact_data.get("is_open_profile", existing.is_open_profile)
            existing.is_recruiter = self._is_recruiter_title(title)
            existing.followers = contact_data.get("followers", existing.followers)
            existing.location = contact_data.get("location", existing.location)
            existing.recent_posts = contact_data.get("recent_posts", existing.recent_posts)
            existing.contact_score = score
            if email:
                existing.email = email
            existing.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Updated existing contact: {existing.name} at {company_name}, score={score}")
            return existing

        # Create new contact
        contact = ContactORM(
            name=contact_data["name"],
            title=title,
            company_id=company.id if company else None,
            company_name=company_name,
            linkedin_url=contact_data.get("linkedin_url", ""),
            linkedin_degree=contact_data.get("linkedin_degree"),
            is_open_profile=contact_data.get("is_open_profile", False),
            is_recruiter=self._is_recruiter_title(title),
            followers=contact_data.get("followers"),
            location=contact_data.get("location", ""),
            recent_posts=contact_data.get("recent_posts", ""),
            email=email,
            contact_score=score,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.session.add(contact)
        self.session.commit()
        logger.info(f"Recorded contact: {contact.name} ({title}) at {company_name}, score={score}")
        return contact

    def enrich_email(self, contact_name: str, company_name: str) -> str | None:
        """Look up and store email for a contact using EmailEnricher.

        Returns the discovered email address, or None if not found.
        """
        from src.integrations.email_enrichment import EmailEnricher

        enricher = EmailEnricher(self.session)
        return enricher.enrich_contact(contact_name, company_name)

    def rank_contacts(self, company_name: str) -> list[ContactORM]:
        """Return contacts for a company sorted by contact_score desc."""
        company = self._get_company(company_name)
        if company:
            return self.session.query(ContactORM).filter(
                ContactORM.company_id == company.id
            ).order_by(ContactORM.contact_score.desc()).all()
        return self.session.query(ContactORM).filter(
            ContactORM.company_name.ilike(company_name.strip())
        ).order_by(ContactORM.contact_score.desc()).all()

    def check_profile_viewers(self) -> dict:
        """Return Premium 'Who Viewed' URL and template for manual data entry."""
        return {
            "viewers_url": "https://www.linkedin.com/me/profile-views/",
            "instructions": (
                "1. Open the URL above in your browser\n"
                "2. For each viewer from a target company, note:\n"
                "   - Name, Title, Company\n"
                "   - Connection degree\n"
                "3. Use record_contact() to save warm leads"
            ),
            "template": {
                "name": "",
                "title": "",
                "linkedin_url": "",
                "linkedin_degree": None,
                "is_open_profile": False,
                "followers": None,
                "location": "",
                "recent_posts": "",
            },
        }

    def update_score_from_response(self, contact_name: str, company_name: str, classification: str) -> ContactORM | None:
        """Adjust contact score based on response classification.

        classification: "POSITIVE", "NEGATIVE", "NEUTRAL", "REFERRAL", "AUTO_REPLY"
        """
        contact = self.session.query(ContactORM).filter(
            ContactORM.name == contact_name,
            ContactORM.company_name == company_name,
        ).first()

        if not contact:
            logger.warning(f"Contact not found: {contact_name} at {company_name}")
            return None

        adjustments = {
            "POSITIVE": 15.0,
            "REFERRAL": 10.0,
            "NEUTRAL": 0.0,
            "AUTO_REPLY": 0.0,
            "NEGATIVE": -10.0,
        }

        delta = adjustments.get(classification, 0.0)
        contact.contact_score = min(max(contact.contact_score + delta, 0.0), 100.0)
        contact.updated_at = datetime.now()
        self.session.commit()
        logger.info(f"Updated score for {contact_name}: {delta:+.1f} -> {contact.contact_score}")
        return contact

    def record_mutual_connections(self, contact_name: str, company_name: str, mutuals: list[str]) -> ContactORM | None:
        """Record mutual connections for a contact."""
        contact = self.session.query(ContactORM).filter(
            ContactORM.name == contact_name,
            ContactORM.company_name == company_name,
        ).first()

        if not contact:
            logger.warning(f"Contact not found: {contact_name} at {company_name}")
            return None

        contact.mutual_connections = ", ".join(mutuals)
        contact.updated_at = datetime.now()
        self.session.commit()
        logger.info(f"Recorded {len(mutuals)} mutual connections for {contact_name}")
        return contact

    def _get_title_priority(self, title: str) -> int:
        """Get priority for a title (lower = better). Returns 99 for unknown."""
        title_lower = title.lower()
        for known_title, priority in TITLE_PRIORITY.items():
            if known_title.lower() in title_lower:
                return priority
        return 99

    def _is_recruiter_title(self, title: str) -> bool:
        """Check if title indicates a recruiter."""
        recruiter_keywords = ["recruiter", "talent", "hr manager", "people ops"]
        return any(kw in title.lower() for kw in recruiter_keywords)

    def _calculate_contact_score(self, priority: int, data: dict) -> float:
        """Calculate contact score (0-100) based on title priority and attributes."""
        if priority <= 1:
            score = 50.0
        elif priority <= 2:
            score = 40.0
        elif priority <= 3:
            score = 30.0
        elif priority <= 4:
            score = 20.0
        elif priority <= 5:
            score = 15.0
        else:
            score = 5.0

        degree = data.get("linkedin_degree")
        if degree == 1:
            score += 20.0
        elif degree == 2:
            score += 10.0
        elif degree == 3:
            score += 5.0

        if data.get("is_open_profile"):
            score += 10.0
        if data.get("recent_posts"):
            score += 10.0

        followers = data.get("followers") or 0
        if followers >= 5000:
            score += 10.0
        elif followers >= 1000:
            score += 5.0
        elif followers >= 500:
            score += 2.0

        return min(score, 100.0)
