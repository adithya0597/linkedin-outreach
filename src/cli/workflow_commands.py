"""Workflow CLI commands: workflow-next, check-config, pipeline-status."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command(name="workflow-next")
def workflow_next():
    """Show the suggested next action based on current pipeline state."""
    from sqlalchemy import func

    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import CompanyORM, OutreachORM, ScanORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    try:
        # Gather stats
        total_companies = session.query(func.count(CompanyORM.id)).scalar() or 0
        disqualified = (
            session.query(func.count(CompanyORM.id))
            .filter(CompanyORM.is_disqualified == True)  # noqa: E712
            .scalar()
            or 0
        )
        active = total_companies - disqualified

        # Decision tree
        suggestion = None
        detail = None

        # 1. No scans in last 24h?
        cutoff = datetime.now() - timedelta(hours=24)
        recent_scans = (
            session.query(func.count(ScanORM.id))
            .filter(ScanORM.started_at >= cutoff)
            .scalar()
            or 0
        )
        if recent_scans == 0:
            suggestion = "Run daily scan"
            detail = "No scans in the last 24 hours. Run: `python -m src.cli.main daily-run`"

        # 2. H1B unknown companies
        if suggestion is None:
            h1b_unknown = (
                session.query(func.count(CompanyORM.id))
                .filter(
                    CompanyORM.h1b_status == "Unknown",
                    CompanyORM.is_disqualified == False,  # noqa: E712
                )
                .scalar()
                or 0
            )
            if h1b_unknown > 0:
                suggestion = "Verify H1B status"
                detail = (
                    f"{h1b_unknown} companies with unknown H1B status. "
                    "Run: `python -m src.cli.main enrich-h1b`"
                )

        # 3. Low data completeness
        if suggestion is None:
            low_completeness = (
                session.query(func.count(CompanyORM.id))
                .filter(CompanyORM.data_completeness < 0.6)
                .scalar()
                or 0
            )
            if low_completeness > 0:
                suggestion = "Enrich company data"
                detail = f"Enrich data for {low_completeness} companies with low completeness (<60%)"

        # 4. Missing hiring managers
        if suggestion is None:
            no_hiring_mgr = (
                session.query(func.count(CompanyORM.id))
                .filter(
                    CompanyORM.hiring_manager == "",
                    CompanyORM.is_disqualified == False,  # noqa: E712
                )
                .scalar()
                or 0
            )
            if no_hiring_mgr > 0:
                suggestion = "Find hiring managers"
                detail = f"{no_hiring_mgr} active companies without a hiring manager contact"

        # 5. Ready outreach records
        if suggestion is None:
            ready_outreach = (
                session.query(func.count(OutreachORM.id))
                .filter(OutreachORM.stage == "READY")
                .scalar()
                or 0
            )
            if ready_outreach > 0:
                suggestion = "Send outreach"
                detail = f"Send outreach to {ready_outreach} ready contacts"

        # 6. Default
        if suggestion is None:
            suggestion = "All caught up!"
            detail = "All caught up! Consider running a portal scan."

        # Display
        panel_content = f"[bold cyan]{suggestion}[/bold cyan]\n\n{detail}"
        panel_content += f"\n\n[dim]Stats: {active} active companies, {disqualified} disqualified, {recent_scans} scans in last 24h[/dim]"

        console.print(Panel(panel_content, title="Next Action", border_style="green"))

    finally:
        session.close()


@app.command(name="check-config")
def check_config():
    """Validate environment setup: env vars, config files, DB, Chrome."""
    table = Table(title="Configuration Check")
    table.add_column("Status", justify="center", width=6)
    table.add_column("Item", style="bold")
    table.add_column("Detail")

    ok = "[green]\u2713[/green]"
    fail = "[red]\u2717[/red]"

    # 1. Environment variables
    for var in ["NOTION_API_KEY", "NOTION_DATABASE_ID", "APIFY_TOKEN"]:
        val = os.environ.get(var)
        if val:
            masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
            table.add_row(ok, f"Env: {var}", f"Set ({masked})")
        else:
            table.add_row(fail, f"Env: {var}", "Not set")

    # 2. Config file
    portals_path = Path("config/portals.yaml")
    if portals_path.exists():
        try:
            import yaml

            with open(portals_path) as f:
                yaml.safe_load(f)
            table.add_row(ok, "Config: portals.yaml", str(portals_path))
        except ImportError:
            table.add_row(ok, "Config: portals.yaml", "Exists (YAML parser not available)")
        except Exception as e:
            table.add_row(fail, "Config: portals.yaml", f"Invalid YAML: {e}")
    else:
        table.add_row(fail, "Config: portals.yaml", "File not found")

    # 3. Database
    db_path = Path("data/outreach.db")
    if db_path.exists():
        size_kb = db_path.stat().st_size / 1024
        try:
            from src.db.database import get_engine

            engine = get_engine()
            from sqlalchemy import inspect

            inspector = inspect(engine)
            tables = inspector.get_table_names()
            table.add_row(
                ok,
                "Database: outreach.db",
                f"{size_kb:.0f} KB, {len(tables)} tables",
            )
        except Exception as e:
            table.add_row(fail, "Database: outreach.db", f"Error: {e}")
    else:
        table.add_row(fail, "Database: outreach.db", "File not found")

    # 4. Chrome
    chrome_path = Path("/Applications/Google Chrome.app/")
    if chrome_path.exists():
        table.add_row(ok, "Chrome: Google Chrome.app", "Installed")
    else:
        table.add_row(fail, "Chrome: Google Chrome.app", "Not found (Playwright needs it)")

    console.print(table)


@app.command(name="pipeline-status")
def pipeline_status():
    """Show last pipeline run results and aggregate company stats."""
    from sqlalchemy import func

    from src.db.database import get_engine, get_session, init_db
    from src.db.orm import CompanyORM, ScanORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    try:
        # --- Recent scans ---
        recent_scans = (
            session.query(ScanORM)
            .order_by(ScanORM.started_at.desc())
            .limit(10)
            .all()
        )

        scan_table = Table(title="Recent Scans (last 10)")
        scan_table.add_column("Portal", style="bold")
        scan_table.add_column("Type")
        scan_table.add_column("Found", justify="right")
        scan_table.add_column("Duration", justify="right")
        scan_table.add_column("Healthy", justify="center")
        scan_table.add_column("Started At")

        if recent_scans:
            for scan in recent_scans:
                duration_str = f"{scan.duration_seconds:.1f}s" if scan.duration_seconds else "N/A"
                healthy = "[green]\u2713[/green]" if scan.is_healthy else "[red]\u2717[/red]"
                started = scan.started_at.strftime("%Y-%m-%d %H:%M") if scan.started_at else "N/A"
                scan_table.add_row(
                    scan.portal or "Unknown",
                    scan.scan_type or "full",
                    str(scan.companies_found or 0),
                    duration_str,
                    healthy,
                    started,
                )
        else:
            scan_table.add_row("--", "--", "--", "--", "--", "No scans recorded")

        console.print(scan_table)
        console.print()

        # --- Company stats ---
        total = session.query(func.count(CompanyORM.id)).scalar() or 0
        disqualified = (
            session.query(func.count(CompanyORM.id))
            .filter(CompanyORM.is_disqualified == True)  # noqa: E712
            .scalar()
            or 0
        )

        # By stage
        stages = (
            session.query(CompanyORM.stage, func.count(CompanyORM.id))
            .group_by(CompanyORM.stage)
            .all()
        )

        # By tier
        tiers = (
            session.query(CompanyORM.tier, func.count(CompanyORM.id))
            .group_by(CompanyORM.tier)
            .all()
        )

        stats_table = Table(title="Company Statistics")
        stats_table.add_column("Metric", style="bold")
        stats_table.add_column("Value", justify="right")

        stats_table.add_row("Total Companies", str(total))
        stats_table.add_row("Active", str(total - disqualified))
        stats_table.add_row("Disqualified", str(disqualified))

        stats_table.add_row("", "")  # spacer
        stats_table.add_row("[bold]By Stage[/bold]", "")
        for stage_name, count in sorted(stages, key=lambda x: x[1], reverse=True):
            stats_table.add_row(f"  {stage_name or 'Unknown'}", str(count))

        stats_table.add_row("", "")  # spacer
        stats_table.add_row("[bold]By Tier[/bold]", "")
        for tier_name, count in sorted(tiers, key=lambda x: x[1], reverse=True):
            stats_table.add_row(f"  {tier_name or 'Unknown'}", str(count))

        console.print(stats_table)
        console.print()

        # --- Last sync timestamp ---
        sync_state_path = Path.home() / ".cache" / "lineked-outreach" / "sync_state.json"
        if sync_state_path.exists():
            try:
                with open(sync_state_path) as f:
                    sync_data = json.load(f)
                last_sync = sync_data.get("last_sync", "Unknown")
                console.print(f"[dim]Last Notion sync: {last_sync}[/dim]")
            except (json.JSONDecodeError, KeyError):
                console.print("[dim]Last Notion sync: sync_state.json exists but unreadable[/dim]")
        else:
            console.print("[dim]Last Notion sync: No sync state file found[/dim]")

    finally:
        session.close()
