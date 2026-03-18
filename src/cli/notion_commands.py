"""Notion CRM sync CLI commands."""

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.command(name="sync-notion")
def sync_notion(
    direction: str = typer.Option("push", help="'push', 'pull', or 'both'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show Notion properties without API calls"),
):
    """Sync data with Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.integrations.notion_sync import NotionCRM

    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    crm = NotionCRM(api_key=api_key or "dry-run", database_id=database_id)
    engine = get_engine()
    session = get_session(engine)

    if dry_run:
        companies = session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).limit(5).all()
        console.print(f"[bold]Dry run — showing Notion properties for {len(companies)} companies:[/bold]\n")
        for comp in companies:
            props = asyncio.run(crm.sync_company(comp, dry_run=True))
            console.print(f"[bold]{comp.name}[/bold]")
            for key, val in props.items():
                console.print(f"  {key}: {val}")
            console.print()
        session.close()
        return

    if direction in ("push", "both"):
        companies = session.query(CompanyORM).filter(
            CompanyORM.is_disqualified == False  # noqa: E712
        ).all()
        console.print(f"[bold]Pushing {len(companies)} companies to Notion...[/bold]")
        page_ids = asyncio.run(crm.push_all(companies))
        console.print(f"[green]Pushed {len(page_ids)} companies.[/green]")

    if direction in ("pull", "both"):
        console.print("[bold]Pulling from Notion...[/bold]")
        pages = asyncio.run(crm.pull_all())
        console.print(f"[green]Pulled {len(pages)} records from Notion.[/green]")
        for page in pages[:5]:
            console.print(f"  {page.get('name', '?')} — {page.get('tier', '?')}")
        if len(pages) > 5:
            console.print(f"  ... and {len(pages) - 5} more")

    session.close()


@app.command(name="sync-notion-full")
def sync_notion_full(
    strategy: str = typer.Option("NEWEST_WINS", "--strategy", help="Conflict strategy: LOCAL_WINS, NOTION_WINS, NEWEST_WINS"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Detect conflicts without merging"),
):
    """Bidirectional Notion sync with conflict resolution."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.notion_bidirectional import NotionBidirectionalSync

    api_key = os.getenv("NOTION_API_KEY", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = NotionBidirectionalSync(
        api_key=api_key or "dry-run",
        database_id=db_id,
        session=session,
    )

    result = asyncio.run(sync.full_sync(strategy=strategy, dry_run=dry_run))

    mode = " (DRY RUN)" if dry_run else ""
    console.print(f"\n[bold]Bidirectional Notion Sync{mode}[/bold]")
    console.print(f"  Pulled: {result['pulled']}")
    console.print(f"  Conflicts found: {result['conflicts_found']}")
    console.print(f"  Merged: {result['merged']}")
    console.print(f"  Strategy: {result['strategy_used']}")
    pushed = result.get("pushed", 0)
    push_errors = result.get("push_errors", [])
    console.print(f"  Pushed to Notion: {pushed}")
    if push_errors:
        console.print(f"  [yellow]Push errors: {len(push_errors)}[/yellow]")
        for err in push_errors[:5]:
            console.print(f"    - {err}")

    session.close()


@app.command(name="sync-contacts")
def sync_contacts(
    direction: str = typer.Option("push", help="'push', 'pull', or 'both'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show properties without API calls"),
):
    """Sync contacts with Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.notion_contacts import NotionContactSync

    api_key = os.getenv("NOTION_API_KEY", "")
    contacts_db_id = os.getenv("NOTION_CONTACTS_DB_ID", "")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return
    if not contacts_db_id and not dry_run:
        console.print("[red]NOTION_CONTACTS_DB_ID not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = NotionContactSync(
        api_key=api_key or "dry-run",
        contacts_database_id=contacts_db_id or "dry-run",
        session=session,
    )

    if direction in ("push", "both"):
        result = asyncio.run(sync.push_all_contacts(dry_run=dry_run))
        console.print(f"[green]Pushed: {result['pushed']}[/green], Skipped: {result['skipped']}")
        if result["errors"]:
            for err in result["errors"]:
                console.print(f"  [red]{err}[/red]")

    if direction in ("pull", "both"):
        contacts_list = asyncio.run(sync.pull_all_contacts())
        console.print(f"[green]Pulled {len(contacts_list)} contacts from Notion.[/green]")

    session.close()


@app.command(name="sync-outreach")
def sync_outreach(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show sync plan without API calls"),
):
    """Push outreach stages to Notion CRM."""
    import asyncio
    import os

    from src.db.database import get_engine, get_session, init_db
    from src.integrations.outreach_sync import OutreachNotionSync

    api_key = os.getenv("NOTION_API_KEY", "")
    db_id = os.getenv("NOTION_DATABASE_ID", "")

    if not api_key and not dry_run:
        console.print("[red]NOTION_API_KEY not set in environment.[/red]")
        return

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    sync = OutreachNotionSync(
        api_key=api_key or "dry-run",
        applications_db_id=db_id,
        session=session,
    )

    result = asyncio.run(sync.sync_all_outreach_stages(dry_run=dry_run))
    mode = " (DRY RUN)" if dry_run else ""

    console.print(f"\n[bold]Outreach -> Notion Sync{mode}[/bold]")
    console.print(f"  Synced: [green]{result['synced']}[/green]")
    console.print(f"  Skipped: {result['skipped']}")
    if result["errors"]:
        console.print(f"  Errors: [red]{len(result['errors'])}[/red]")
        for err in result["errors"]:
            console.print(f"    {err}")

    console.print(f"\n  Stage counts: {result['stage_counts']}")
    session.close()


@app.command(name="notion-incremental")
def notion_incremental(
    reset: bool = typer.Option(False, "--reset", help="Reset sync state"),
    status: bool = typer.Option(False, "--status", help="Show sync state"),
):
    """Manage incremental Notion sync."""
    from src.integrations.notion_incremental import NotionSyncState

    state = NotionSyncState()
    if reset:
        state.reset()
        console.print("[green]Notion sync state reset.[/green]")
    elif status:
        info = state.get_status()
        last = info.get("last_sync")
        if last:
            console.print(f"[bold]Last sync:[/bold] {last}")
        else:
            console.print("[yellow]No sync recorded yet.[/yellow]")
    else:
        console.print("[yellow]Use --reset or --status.[/yellow]")
