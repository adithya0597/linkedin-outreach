"""MCP Playwright scraper stub.

This is a thin wrapper that represents portals scanned via MCP Playwright
skills (Claude Code slash commands). The actual scraping logic lives in
.claude/commands/scan-*.md skill files — not in Python code.

These stub scrapers serve two purposes:
1. Registry integration: They appear in the PortalRegistry so the CLI
   can list them and track their health status.
2. MCP bridge: When results are saved by a skill, the mcp_bridge module
   persists them to SQLite via persist_scan_results().

For actual scanning, use the corresponding slash command:
- LinkedIn: /scan-linkedin
- Built In: /scan-builtin
- JobBoard AI: /scan-jobboard-ai
"""

from __future__ import annotations

from loguru import logger

from src.config.enums import SourcePortal
from src.models.job_posting import JobPosting
from src.scrapers.base_scraper import BaseScraper
from src.scrapers.rate_limiter import RateLimiter


class MCPPlaywrightScraper(BaseScraper):
    """Stub scraper for portals handled by MCP Playwright skills.

    search() is a no-op — actual scanning happens via Claude Code slash commands.
    The scraper is registered so it appears in portal listings and health checks.
    """

    def __init__(
        self,
        portal: SourcePortal,
        skill_name: str = "",
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(portal, rate_limiter=rate_limiter)
        self._skill_name = skill_name or f"scan-{portal.value.lower().replace(' ', '-')}"

    def is_healthy(self) -> bool:
        """MCP scrapers are always 'healthy' — they rely on external browser sessions."""
        return True

    async def search(self, keywords: list[str], days: int = 30) -> list[JobPosting]:
        """No-op: MCP Playwright scanning is done via slash commands.

        Use the corresponding skill instead:
            /scan-linkedin, /scan-builtin, /scan-jobboard-ai, etc.

        Results are persisted via:
            python -m src.cli.main mcp-persist <portal> <json_path>
        """
        logger.info(
            f"{self.name} is an MCP Playwright portal — "
            f"use /{self._skill_name} skill to scan, not programmatic search()"
        )
        return []

