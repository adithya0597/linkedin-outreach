"""Email enrichment — pluggable email finder with Hunter.io backend."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from src.db.orm import CompanyORM, ContactORM


@runtime_checkable
class EmailEnrichmentBackend(Protocol):
    """Protocol for email enrichment backends."""
    def find_email(self, first_name: str, last_name: str, domain: str) -> str | None: ...


class HunterIOBackend:
    """Hunter.io email finder backend."""

    BASE_URL = "https://api.hunter.io/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("HUNTER_API_KEY", "")
        self._client = httpx.Client(timeout=10)

    def find_email(self, first_name: str, last_name: str, domain: str) -> str | None:
        """Call Hunter.io email-finder endpoint."""
        if not self.api_key:
            logger.warning("No Hunter.io API key configured")
            return None

        try:
            resp = self._client.get(
                f"{self.BASE_URL}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": self.api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            email = data.get("email")
            confidence = data.get("confidence", 0)
            if email and confidence >= 50:
                return email
            return None
        except (httpx.HTTPError, KeyError) as e:
            logger.warning(f"Hunter.io lookup failed: {e}")
            return None

    def verify_email(self, email: str) -> dict:
        """Verify an email address via Hunter.io."""
        if not self.api_key:
            return {"status": "unknown", "reason": "no_api_key"}

        try:
            resp = self._client.get(
                f"{self.BASE_URL}/email-verifier",
                params={"email": email, "api_key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "status": data.get("status", "unknown"),
                "score": data.get("score", 0),
                "disposable": data.get("disposable", False),
            }
        except httpx.HTTPError as e:
            return {"status": "error", "reason": str(e)}


class ManualBackend:
    """Manual/no-op backend — always returns None."""

    def find_email(self, first_name: str, last_name: str, domain: str) -> str | None:
        return None


class EmailEnricher:
    """Enrich contacts with email addresses using a pluggable backend."""

    def __init__(
        self, session: Session, backend: EmailEnrichmentBackend | None = None
    ):
        self.session = session
        self.backend = backend or self._get_default_backend()

    def _get_default_backend(self) -> EmailEnrichmentBackend:
        """Get default backend based on environment."""
        api_key = os.getenv("HUNTER_API_KEY", "")
        if api_key:
            return HunterIOBackend(api_key)
        return ManualBackend()

    def _extract_domain(self, company_name: str) -> str | None:
        """Extract domain from company's website URL."""
        company = (
            self.session.query(CompanyORM)
            .filter(CompanyORM.name.ilike(f"%{company_name}%"))
            .first()
        )
        if company and company.website:
            # Extract domain from URL
            url = company.website.strip()
            if "://" in url:
                url = url.split("://", 1)[1]
            return url.split("/")[0].lower()
        # Fallback: guess domain
        clean = company_name.lower().replace(" ", "").replace(".", "").replace(",", "")
        return f"{clean}.com"

    def enrich_contact(self, contact_name: str, company_name: str) -> str | None:
        """Look up and store email for a contact. Returns email or None."""
        parts = contact_name.strip().split()
        if len(parts) < 2:
            logger.warning(f"Cannot split '{contact_name}' into first/last name")
            return None

        first_name = parts[0]
        last_name = parts[-1]
        domain = self._extract_domain(company_name)

        if not domain:
            return None

        email = self.backend.find_email(first_name, last_name, domain)

        if email:
            # Update ContactORM
            contact = (
                self.session.query(ContactORM)
                .filter(
                    ContactORM.name.ilike(f"%{contact_name}%"),
                    ContactORM.company_name.ilike(f"%{company_name}%"),
                )
                .first()
            )
            if contact:
                contact.email = email
                self.session.commit()
                logger.info(f"Enriched {contact_name} at {company_name}: {email}")

        return email

    def batch_enrich(self, limit: int = 50) -> dict:
        """Enrich all contacts with empty email. Returns {enriched, failed, skipped}."""
        contacts = (
            self.session.query(ContactORM)
            .filter((ContactORM.email == "") | (ContactORM.email.is_(None)))
            .limit(limit)
            .all()
        )

        enriched = 0
        failed = 0
        skipped = 0

        for contact in contacts:
            if not contact.company_name:
                skipped += 1
                continue

            parts = contact.name.strip().split()
            if len(parts) < 2:
                skipped += 1
                continue

            domain = self._extract_domain(contact.company_name)
            if not domain:
                skipped += 1
                continue

            email = self.backend.find_email(parts[0], parts[-1], domain)
            if email:
                contact.email = email
                enriched += 1
            else:
                failed += 1

        if enriched > 0:
            self.session.commit()

        logger.info(f"Batch enrich: {enriched} enriched, {failed} failed, {skipped} skipped")
        return {"enriched": enriched, "failed": failed, "skipped": skipped}
