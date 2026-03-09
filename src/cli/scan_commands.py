"""Scan-related CLI commands: scan, mcp-persist, scan-gmail, rescan, test-antibot."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command()
def scan(
    portal: str = typer.Option("all", help="Portal name or 'all'"),
    tier: int = typer.Option(0, help="Scan only this tier (1-3), 0 for all"),
    scan_type: str = typer.Option("full", help="'full' or 'rescan'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show portals without scanning"),
    keywords: str = typer.Option("", help="Comma-separated keywords (overrides portal config)"),
    smart: bool = typer.Option(False, "--smart", help="Auto-skip demoted portals via PortalScorer"),
    days: int = typer.Option(30, "--days", help="Only include postings from the last N days"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip Notion sync after scan"),
):
    """Scan job portals for new listings."""
    import asyncio
    import time

    import yaml

    from src.db.database import get_engine, get_session, init_db
    from src.scrapers.persistence import persist_scan_results
    from src.scrapers.registry import build_default_registry

    registry = build_default_registry()

    # Select scrapers
    if portal == "all" and tier > 0:
        scrapers = registry.get_scrapers_by_tier(tier)
    elif portal == "all":
        scrapers = registry.get_all_scrapers()
    else:
        try:
            scrapers = [registry.get_scraper(portal)]
        except KeyError:
            console.print(f"[red]Unknown portal: {portal}[/red]")
            console.print(f"Available: {', '.join(s.name for s in registry.get_all_scrapers())}")
            return

    # Dry run — just show portal status
    if dry_run:
        table = Table(title="Portal Scan Status")
        table.add_column("Portal", style="bold")
        table.add_column("Tier")
        table.add_column("Type")
        table.add_column("Status")
        for s in scrapers:
            healthy = "[green]Ready[/green]" if s.is_healthy() else "[red]Down[/red]"
            table.add_row(s.name, str(s.tier.value), type(s).__bases__[0].__name__, healthy)
        console.print(table)
        return

    # Load keywords
    portals_yaml = Path(__file__).parent.parent.parent / "config" / "portals.yaml"
    with open(portals_yaml) as f:
        portals_config = yaml.safe_load(f)

    # Build per-portal keyword map from config
    portal_keywords: dict[str, list[str]] = {}
    for key, cfg in portals_config.get("portals", {}).items():
        portal_keywords[cfg.get("name", key)] = cfg.get(
            "search_keywords", ["AI Engineer", "ML Engineer"]
        )

    # CLI override applies to all portals
    kw_override = [k.strip() for k in keywords.split(",")] if keywords else None

    # Run scan
    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    # Smart scan — filter out demoted portals
    if smart:
        from src.pipeline.smart_scan import SmartScanOrchestrator

        orchestrator = SmartScanOrchestrator(session)
        smart_list = orchestrator.get_smart_portal_list()
        scrapers = [s for s in scrapers if s.name in smart_list]
        console.print(f"[bold]Smart scan: using {len(scrapers)} portals (demoted excluded)[/bold]")

    async def _run_scans() -> None:
        results_table = Table(title="Scan Results")
        results_table.add_column("Portal", style="bold")
        results_table.add_column("Found", justify="right")
        results_table.add_column("New", justify="right")
        results_table.add_column("Time", justify="right")
        results_table.add_column("Status")

        total_found = 0
        total_new = 0

        for s in scrapers:
            if not s.is_healthy():
                results_table.add_row(s.name, "-", "-", "-", "[red]Skipped (unhealthy)[/red]")
                continue

            portal_kws = kw_override or portal_keywords.get(s.name, ["AI Engineer", "ML Engineer"])

            start = time.time()
            try:
                postings = await s.search(portal_kws, days=days)
                elapsed = time.time() - start
                found, new, new_co = persist_scan_results(
                    session, s.name, postings, scan_type, elapsed
                )
                total_found += found
                total_new += new
                results_table.add_row(
                    s.name,
                    str(found),
                    f"[green]{new}[/green]",
                    f"{elapsed:.1f}s",
                    "[green]OK[/green]",
                )
            except Exception as e:
                elapsed = time.time() - start
                persist_scan_results(session, s.name, [], scan_type, elapsed, errors=str(e))
                results_table.add_row(
                    s.name, "0", "0", f"{elapsed:.1f}s", f"[red]Error: {e}[/red]"
                )

        console.print(results_table)
        console.print(f"\n[bold]Total: {total_found} found, {total_new} new[/bold]")

    asyncio.run(_run_scans())

    if not no_sync:
        from src.cli._db import auto_sync
        auto_sync(session)

    session.close()


@app.command(name="mcp-persist")
def mcp_persist(
    portal: str = typer.Argument(help="Portal name (e.g., 'linkedin', 'wellfound')"),
    json_path: str = typer.Argument(help="Path to MCP results JSON file"),
):
    """Persist MCP Playwright scan results from a JSON file into the database."""
    from src.scrapers.mcp_bridge import persist_mcp_results

    path = Path(json_path)
    if not path.exists():
        console.print(f"[red]File not found: {json_path}[/red]")
        return

    total, new, new_co = persist_mcp_results(portal, json_path)
    console.print(f"[green]Persisted {portal}: {total} found, {new} new postings, {new_co} new companies[/green]")


@app.command(name="scan-gmail")
def scan_gmail(
    max_emails: int = typer.Option(20, help="Max alert emails to process"),
    days: int = typer.Option(7, help="Only process emails from the last N days"),
):
    """Parse LinkedIn Job Alert emails from Gmail and persist to database."""
    import asyncio

    from src.db.database import get_engine, get_session, init_db
    from src.scrapers.linkedin_email_ingest import LinkedInAlertScraper
    from src.scrapers.persistence import persist_scan_results

    console.print("[bold]Scanning LinkedIn Job Alert emails...[/bold]")
    console.print(
        "[yellow]Note: Email HTML must be injected via Gmail MCP first.[/yellow]\n"
        "Use the daily-portal-scanner skill or inject emails manually:\n"
        "  scraper.inject_emails([html1, html2, ...])"
    )

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    scraper = LinkedInAlertScraper()

    async def _run():
        postings = await scraper.search([], days=days)
        if postings:
            found, new, new_co = persist_scan_results(
                session, "LinkedIn Alerts", postings, scan_type="gmail"
            )
            console.print(f"[green]Gmail alerts: {found} found, {new} new, {new_co} new companies[/green]")
        else:
            console.print("[yellow]No emails injected — use /scan-linkedin skill for Gmail integration[/yellow]")

    asyncio.run(_run())
    session.close()


@app.command(name="test-antibot")
def test_antibot():
    """Test Patchright stealth browser against bot detection sites."""
    import asyncio

    async def _test():
        try:
            from patchright.async_api import async_playwright

            engine = "Patchright"
        except ImportError:
            from playwright.async_api import async_playwright

            engine = "Playwright (fallback)"

        console.print(f"[bold]Testing {engine} against bot detection...[/bold]")

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = await browser.new_page()

        # Test 1: bot.sannysoft.com
        console.print("\n[cyan]Test 1: bot.sannysoft.com[/cyan]")
        await page.goto("https://bot.sannysoft.com")
        await page.wait_for_timeout(3000)
        webdriver = await page.evaluate("() => navigator.webdriver")
        console.print(f"  navigator.webdriver: {webdriver} {'[green]PASS[/green]' if not webdriver else '[red]FAIL[/red]'}")

        # Test 2: Check CDP detection
        console.print("\n[cyan]Test 2: CDP Runtime.enable leak[/cyan]")
        cdp_check = await page.evaluate("""() => {
            try {
                return window.chrome && window.chrome.runtime ? 'detected' : 'clean';
            } catch(e) { return 'clean'; }
        }""")
        console.print(f"  CDP leak: {cdp_check}")

        await browser.close()
        await pw.stop()
        console.print(f"\n[bold green]Anti-bot test complete ({engine})[/bold green]")

    asyncio.run(_test())


@app.command()
def rescan(
    smart: bool = typer.Option(True, help="Use smart portal selection (promoted + afternoon list)"),
    h1b: bool = typer.Option(True, "--h1b/--no-h1b", help="Run H1B enrichment after scan"),
    keywords: str = typer.Option("", help="Comma-separated keywords"),
):
    """Afternoon rescan of high-velocity portals with smart filtering."""
    import asyncio

    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.smart_scan import SmartScanOrchestrator

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    orchestrator = SmartScanOrchestrator(session)

    if smart:
        portals = orchestrator.get_rescan_portals()
        console.print(f"[bold]Smart rescan: {len(portals)} portals[/bold]")
        for p in portals:
            console.print(f"  {p}")
    else:
        portals = None

    kws = [k.strip() for k in keywords.split(",")] if keywords else None

    result = asyncio.run(orchestrator.run_smart_scan(
        portals=portals,
        keywords=kws,
        enrich_h1b=h1b,
        scan_type="rescan",
    ))

    scan = result["scan_results"]
    console.print(f"\n[bold]Results:[/bold] {scan.get('total_found', 0)} found, {scan.get('total_new', 0)} new")
    if result["h1b_enriched"]:
        console.print(f"[green]H1B enriched: {result['h1b_enriched']} companies[/green]")
    if result["skipped_portals"]:
        console.print(f"[yellow]Skipped (demoted): {', '.join(result['skipped_portals'])}[/yellow]")

    session.close()
