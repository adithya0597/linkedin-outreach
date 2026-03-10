"""Tests for LinkedIn email alert ingest (src/scrapers/linkedin_email_ingest.py)
and Gmail alert parser (src/integrations/gmail_alert_parser.py)."""

from __future__ import annotations

import pytest

from src.config.enums import SourcePortal
from src.integrations.gmail_alert_parser import (
    AlertJob,
    _clean_linkedin_url,
    parse_alert_subject,
    parse_linkedin_alert_html,
)
from src.models.job_posting import JobPosting
from src.scrapers.linkedin_email_ingest import LinkedInAlertScraper

# ---------------------------------------------------------------------------
# Gmail alert parser: parse_linkedin_alert_html
# ---------------------------------------------------------------------------


SAMPLE_LINKEDIN_ALERT_HTML = """
<html>
<body>
<table>
  <tr>
    <td>
      <div>
        <a href="https://www.linkedin.com/comm/jobs/view/1234567890?tracking=abc123">
          AI Engineer
        </a>
        <span>Acme AI Corp</span>
        <span>San Francisco, CA</span>
      </div>
    </td>
  </tr>
  <tr>
    <td>
      <div>
        <a href="https://www.linkedin.com/jobs/view/9876543210?utm_source=email">
          ML Platform Engineer
        </a>
        <span>Beta ML Inc</span>
        <span>Remote - US</span>
        <span>$150,000 - $200,000/yr</span>
      </div>
    </td>
  </tr>
  <tr>
    <td>
      <div>
        <a href="https://www.linkedin.com/jobs/view/5555555555">
          Senior Data Scientist
        </a>
        <span>Gamma Analytics</span>
        <span>New York, NY</span>
      </div>
    </td>
  </tr>
</table>
</body>
</html>
"""


class TestParseLinkedInAlertHtml:
    def test_parse_linkedin_alert_empty_html(self):
        """Empty string returns empty list."""
        result = parse_linkedin_alert_html("")
        assert result == []

    def test_parse_linkedin_alert_none_like_empty(self):
        """Empty/whitespace-only HTML returns empty list."""
        result = parse_linkedin_alert_html("   ")
        assert result == []

    def test_parse_linkedin_alert_with_jobs(self):
        """HTML with LinkedIn job links returns AlertJob list."""
        jobs = parse_linkedin_alert_html(SAMPLE_LINKEDIN_ALERT_HTML)

        assert isinstance(jobs, list)
        assert len(jobs) >= 2  # At least the jobs with valid titles

        # Verify AlertJob objects have expected structure
        for job in jobs:
            assert isinstance(job, AlertJob)
            assert job.title  # Non-empty title
            assert "linkedin.com/jobs/view/" in job.url

    def test_parse_linkedin_alert_deduplicates_urls(self):
        """Duplicate job URLs in the same email should be deduplicated."""
        html = """
        <html><body>
        <a href="https://www.linkedin.com/jobs/view/111">AI Engineer</a>
        <a href="https://www.linkedin.com/jobs/view/111">AI Engineer</a>
        <a href="https://www.linkedin.com/jobs/view/222">ML Engineer</a>
        </body></html>
        """
        jobs = parse_linkedin_alert_html(html)
        urls = [j.url for j in jobs]
        assert len(urls) == len(set(urls)), "URLs should be unique"

    def test_parse_linkedin_alert_skips_short_titles(self):
        """Links with very short text (< 3 chars) should be skipped."""
        html = """
        <html><body>
        <a href="https://www.linkedin.com/jobs/view/111">AI</a>
        <a href="https://www.linkedin.com/jobs/view/222">Senior AI Platform Engineer</a>
        </body></html>
        """
        jobs = parse_linkedin_alert_html(html)
        # "AI" is only 2 chars, should be skipped
        titles = [j.title for j in jobs]
        assert "AI" not in titles
        assert any("Senior AI Platform Engineer" in t for t in titles)


# ---------------------------------------------------------------------------
# Gmail alert parser: _clean_linkedin_url
# ---------------------------------------------------------------------------


class TestCleanLinkedInUrl:
    def test_clean_linkedin_url(self):
        """Extracts clean job URL from tracking link."""
        tracked = "https://www.linkedin.com/comm/jobs/view/12345?trackingId=abc&refId=xyz"
        clean = _clean_linkedin_url(tracked)
        assert clean == "https://www.linkedin.com/jobs/view/12345"

    def test_clean_linkedin_url_already_clean(self):
        """Already clean URL is returned as-is (minus /comm/)."""
        url = "https://www.linkedin.com/jobs/view/67890"
        clean = _clean_linkedin_url(url)
        assert clean == "https://www.linkedin.com/jobs/view/67890"

    def test_clean_linkedin_url_removes_comm(self):
        """The /comm/ prefix is removed from LinkedIn URLs."""
        url = "https://www.linkedin.com/comm/jobs/view/12345"
        clean = _clean_linkedin_url(url)
        assert "/comm/" not in clean
        assert "12345" in clean

    def test_clean_linkedin_url_invalid(self):
        """Non-LinkedIn job URL returns empty string."""
        url = "https://www.google.com/search?q=jobs"
        clean = _clean_linkedin_url(url)
        assert clean == ""


# ---------------------------------------------------------------------------
# Gmail alert parser: parse_alert_subject
# ---------------------------------------------------------------------------


class TestParseAlertSubject:
    def test_parse_alert_subject_standard_format(self):
        """Parses '3 new jobs for AI Engineer in United States'."""
        result = parse_alert_subject("3 new jobs for AI Engineer in United States")
        assert result["count"] == "3"
        assert result["keyword"] == "AI Engineer"
        assert result["location"] == "United States"

    def test_parse_alert_subject_alternate_format(self):
        """Parses 'AI Engineer: 5 new jobs'."""
        result = parse_alert_subject("AI Engineer: 5 new jobs")
        assert result["keyword"] == "AI Engineer"
        assert result["count"] == "5"

    def test_parse_alert_subject_singular_job(self):
        """Parses '1 new job for ML Engineer in San Francisco'."""
        result = parse_alert_subject("1 new job for ML Engineer in San Francisco")
        assert result["count"] == "1"
        assert result["keyword"] == "ML Engineer"
        assert result["location"] == "San Francisco"

    def test_parse_alert_subject_unrecognized(self):
        """Unrecognized subject format returns empty dict."""
        result = parse_alert_subject("Random email subject")
        assert result == {}


# ---------------------------------------------------------------------------
# LinkedInAlertScraper
# ---------------------------------------------------------------------------


class TestLinkedInAlertScraper:
    def test_linkedin_alert_scraper_is_healthy(self):
        """Always returns True -- zero ban risk."""
        scraper = LinkedInAlertScraper()
        assert scraper.is_healthy() is True

    def test_linkedin_alert_scraper_portal(self):
        """Uses LINKEDIN portal since these are LinkedIn jobs."""
        scraper = LinkedInAlertScraper()
        assert scraper.portal == SourcePortal.LINKEDIN

    @pytest.mark.asyncio
    async def test_linkedin_alert_scraper_no_emails(self):
        """search() with no injected emails returns empty list."""
        scraper = LinkedInAlertScraper()
        results = await scraper.search(keywords=["ai"], days=30)
        assert results == []

    @pytest.mark.asyncio
    async def test_linkedin_alert_scraper_with_emails(self):
        """inject_emails + search() returns JobPostings."""
        scraper = LinkedInAlertScraper()
        scraper.inject_emails([SAMPLE_LINKEDIN_ALERT_HTML])

        results = await scraper.search(keywords=["ai"], days=30)

        assert isinstance(results, list)
        assert len(results) >= 1
        for posting in results:
            assert isinstance(posting, JobPosting)
            assert posting.source_portal == SourcePortal.LINKEDIN
            assert posting.title  # Non-empty title
            assert posting.url  # Non-empty URL

    @pytest.mark.asyncio
    async def test_linkedin_alert_scraper_clears_after_search(self):
        """Emails should be cleared after search() processes them."""
        scraper = LinkedInAlertScraper()
        scraper.inject_emails([SAMPLE_LINKEDIN_ALERT_HTML])

        # First search processes injected emails
        results1 = await scraper.search(keywords=["ai"], days=30)
        assert len(results1) >= 1

        # Second search should return empty (emails cleared)
        results2 = await scraper.search(keywords=["ai"], days=30)
        assert results2 == []

    @pytest.mark.asyncio
    async def test_linkedin_alert_scraper_deduplicates_across_emails(self):
        """Duplicate URLs across multiple emails should be deduplicated."""
        scraper = LinkedInAlertScraper()
        # Inject the same HTML twice
        scraper.inject_emails([SAMPLE_LINKEDIN_ALERT_HTML, SAMPLE_LINKEDIN_ALERT_HTML])

        results = await scraper.search(keywords=["ai"], days=30)

        urls = [r.url for r in results]
        assert len(urls) == len(set(urls)), "Duplicate URLs should be removed"
