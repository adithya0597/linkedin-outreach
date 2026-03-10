"""LinkedIn queue and status CLI commands."""

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.command(name="linkedin-queue")
def linkedin_queue_cmd(limit: int = typer.Option(10, "--limit", "-n", help="Max messages to show")):
    """Show LinkedIn outreach queue in copy-paste format."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.send_queue import SendQueueManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    sqm = SendQueueManager(session)
    status = sqm.get_rate_limit_status()
    console.print(f"\n[bold]Rate Limit:[/bold] {status.get('sent_this_week', 0)}/{status.get('limit', 100)} sent this week\n")
    queue = sqm.generate_daily_queue(max_sends=limit)
    if not queue:
        console.print("[yellow]No messages in queue.[/yellow]")
        session.close()
        return
    for i, item in enumerate(queue, 1):
        console.print(f"\n{'='*60}")
        console.print(f"[cyan]#{i}[/cyan] {item.get('company_name', 'N/A')} — {item.get('contact_name', 'N/A')}")
        actions = item.get("linkedin_actions", {})
        console.print(f"Profile: {actions.get('profile_url', 'N/A') if actions else 'N/A'}")
        msg = item.get("content", "")
        console.print(f"Chars: {len(msg)}")
        console.print("--- Copy below ---")
        console.print(msg)
        console.print("--- End ---")
    session.close()


@app.command(name="linkedin-status")
def linkedin_status_cmd():
    """Show outreach status summary by stage."""
    from src.db.database import get_engine, get_session, init_db
    from src.outreach.send_queue import SendQueueManager

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    sqm = SendQueueManager(session)
    summary = sqm.get_outreach_status_summary()
    if not summary:
        console.print("[yellow]No outreach records found.[/yellow]")
        session.close()
        return
    console.print("\n[bold]Outreach Status:[/bold]\n")
    total = sum(summary.values())
    for stage, count in sorted(summary.items()):
        console.print(f"  {stage}: {count}")
    sent = summary.get("Sent", 0)
    responded = summary.get("Responded", 0)
    rate = f"{responded/sent*100:.1f}%" if sent > 0 else "N/A"
    console.print(f"\n  Total: {total} | Response Rate: {rate}")
    session.close()
