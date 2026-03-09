"""Gmail-related CLI commands."""

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command(name="gmail-drafts")
def gmail_drafts(
    batch: bool = typer.Option(False, "--batch", help="Prepare all stale drafts"),
    list_drafts: bool = typer.Option(False, "--list", help="List pending drafts"),
    threshold: int = typer.Option(14, "--threshold", help="Days since last contact"),
):
    """Prepare Gmail drafts from stale outreach connections."""
    from src.db.database import get_session, init_db
    from src.integrations.gmail_bridge import GmailBridge

    if list_drafts:
        bridge = GmailBridge.__new__(GmailBridge)
        pending = bridge.load_pending_drafts()
        if not pending:
            console.print("[yellow]No pending drafts.[/yellow]")
            return
        table = Table(title=f"Pending Gmail Drafts ({len(pending)})")
        table.add_column("To", style="bold")
        table.add_column("Subject")
        table.add_column("Body Preview")
        for d in pending:
            body_preview = (d.get("body", "")[:60] + "...") if len(d.get("body", "")) > 60 else d.get("body", "")
            table.add_row(d.get("to", "—"), d.get("subject", "—"), body_preview)
        console.print(table)
        return

    engine = init_db()
    session = get_session(engine)
    bridge = GmailBridge(session)
    drafts = bridge.prepare_drafts(threshold_days=threshold)
    if not drafts:
        console.print("[yellow]No stale connections to draft.[/yellow]")
        session.close()
        return
    if batch:
        count = bridge.save_drafts(drafts)
        console.print(f"[green]Saved {count} drafts to data/gmail_drafts.json[/green]")
    else:
        console.print(f"[cyan]Found {len(drafts)} drafts. Use --batch to save.[/cyan]")
        for d in drafts[:5]:
            console.print(f"  • {d.get('to', '—')}: {d.get('subject', '—')}")
    session.close()


@app.command(name="enrich-emails")
def enrich_emails(
    company: str = typer.Option("", help="Enrich contacts for a specific company"),
    batch: bool = typer.Option(False, "--batch", help="Batch enrich all contacts"),
    limit: int = typer.Option(50, "--limit", help="Max contacts to enrich"),
):
    """Enrich contact emails via Hunter.io."""
    from src.db.database import get_session, init_db
    from src.integrations.email_enrichment import EmailEnricher

    engine = init_db()
    session = get_session(engine)
    enricher = EmailEnricher(session)

    if company:
        from src.db.orm import ContactORM

        contacts = session.query(ContactORM).filter(
            ContactORM.company_name.ilike(f"%{company}%"),
            (ContactORM.email.is_(None)) | (ContactORM.email == ""),
        ).all()
        if not contacts:
            console.print(f"[yellow]No contacts without email for '{company}'.[/yellow]")
            session.close()
            return
        for c in contacts:
            result = enricher.enrich_contact(c.contact_name, c.company_name)
            status = f"[green]{result}[/green]" if result else "[red]Not found[/red]"
            console.print(f"  {c.contact_name}: {status}")
    elif batch:
        results = enricher.batch_enrich(limit=limit)
        console.print(
            f"[green]Enriched: {results['enriched']}[/green] | "
            f"[red]Failed: {results['failed']}[/red] | "
            f"Skipped: {results['skipped']}"
        )
    else:
        console.print("[yellow]Use --company or --batch to enrich contacts.[/yellow]")
    session.close()


@app.command(name="gmail-send")
def gmail_send_cmd(dry_run: bool = typer.Option(False, "--dry-run", help="Display drafts without send instructions")):
    """Display pending Gmail drafts for MCP sending."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.gmail_bridge import GmailBridge

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    bridge = GmailBridge(session)
    drafts = bridge.load_pending_drafts()
    if not drafts:
        console.print("[yellow]No pending Gmail drafts found.[/yellow]")
        session.close()
        return
    console.print(f"\n[bold]Pending Gmail Drafts ({len(drafts)}):[/bold]\n")
    for i, d in enumerate(drafts, 1):
        console.print(f"[cyan]#{i}[/cyan] To: {d.get('to', 'N/A')} | Subject: {d.get('subject', 'N/A')} | Company: {d.get('company', d.get('metadata', {}).get('company', 'N/A'))}")
        console.print(f"  Body: {d.get('body', '')[:200]}...")
        console.print()
    if not dry_run:
        console.print("[bold green]Next step:[/bold green] Ask Claude to run `gmail_create_draft` MCP tool for each draft above.")
    session.close()


@app.command(name="gmail-mark-sent")
def gmail_mark_sent_cmd(
    all_drafts: bool = typer.Option(False, "--all", help="Mark all pending drafts as sent"),
    company: str = typer.Option(None, "--company", help="Mark drafts for specific company"),
):
    """Mark Gmail drafts as sent and update outreach records."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.gmail_bridge import GmailBridge

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    bridge = GmailBridge(session)
    companies = None
    if company:
        companies = [company]
    elif not all_drafts:
        console.print("[red]Specify --all or --company COMPANY[/red]")
        session.close()
        return
    count = bridge.mark_drafts_sent(companies)
    console.print(f"[green]Marked {count} outreach records as 'Draft Created'[/green]")
    bridge.clear_drafts()
    console.print("[green]Cleared processed drafts from JSON.[/green]")
    session.close()


@app.command(name="check-responses")
def check_responses_cmd():
    """Show pending response checks with Gmail search queries."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.gmail_bridge import ResponseMonitor

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    try:
        monitor = ResponseMonitor(session)
        checks = monitor.get_pending_checks()
        summary = monitor.get_check_summary()

        if not checks:
            console.print("[yellow]No sent outreach awaiting response checks.[/yellow]")
            return

        console.print(f"\n[bold]Pending Response Checks ({summary['total_sent']}):[/bold]")
        console.print(f"  With email: {summary['with_email']} | Without email: {summary['without_email']}\n")

        for i, c in enumerate(checks, 1):
            email_str = c["email"] or "[no email]"
            query_str = c["search_query"] or "[no search query - need email]"
            console.print(f"[cyan]#{i}[/cyan] {c['company']} — {c['contact']} ({email_str})")
            console.print(f"  Sent: {c['sent_date']} | Waiting: {c['days_waiting']} days")
            console.print(f"  Gmail search: {query_str}")
            console.print()

        console.print("[bold green]Next steps:[/bold green]")
        console.print("  1. Ask Claude to search Gmail with each query via `gmail_search_messages` MCP")
        console.print("  2. For each reply found, run: outreach log-response <company> --text 'reply text'")
    finally:
        session.close()
