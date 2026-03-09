"""Contact management CLI commands."""

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command()
def contacts(
    company: str = typer.Argument(help="Company name to find contacts for"),
):
    """Generate LinkedIn search URLs for hiring contacts at a company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    results = researcher.find_hiring_contacts(company)

    table = Table(title=f"LinkedIn Search URLs — {company}")
    table.add_column("Priority", justify="right")
    table.add_column("Title", style="bold")
    table.add_column("Search URL")

    for r in results:
        table.add_row(str(r["priority"]), r["title"], r["search_url"])

    console.print(table)
    session.close()


@app.command(name="record-contact")
def record_contact(
    company: str = typer.Argument(help="Company name"),
    name: str = typer.Argument(help="Contact name"),
    title: str = typer.Argument(help="Contact title (e.g. CTO, Recruiter)"),
    linkedin_url: str = typer.Option("", help="LinkedIn profile URL"),
    degree: int = typer.Option(None, help="LinkedIn connection degree (1, 2, or 3)"),
    open_profile: bool = typer.Option(False, help="Is an Open Profile (free InMail)"),
):
    """Record a contact for a target company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)

    contact = researcher.record_contact(company, {
        "name": name,
        "title": title,
        "linkedin_url": linkedin_url,
        "linkedin_degree": degree,
        "is_open_profile": open_profile,
    })

    console.print(f"[green]Recorded:[/green] {contact.name} ({contact.title}) at {company}")
    console.print(f"  Score: {contact.contact_score}, Company ID: {contact.company_id or 'N/A'}")
    session.close()


@app.command(name="rank-contacts")
def rank_contacts(
    company: str = typer.Argument(help="Company name"),
):
    """Show ranked contacts for a company."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    ranked = researcher.rank_contacts(company)

    if not ranked:
        console.print(f"[yellow]No contacts found for {company}.[/yellow]")
        session.close()
        return

    table = Table(title=f"Contacts — {company}")
    table.add_column("#", justify="right")
    table.add_column("Name", style="bold")
    table.add_column("Title")
    table.add_column("Score", justify="right")
    table.add_column("Degree")
    table.add_column("Open Profile")

    for i, c in enumerate(ranked, 1):
        table.add_row(
            str(i), c.name, c.title, f"{c.contact_score}",
            str(c.linkedin_degree or "?"),
            "[green]Yes[/green]" if c.is_open_profile else "No",
        )

    console.print(table)
    session.close()


@app.command()
def viewers():
    """Show LinkedIn Premium 'Who Viewed Your Profile' URL and instructions."""
    from src.db.database import get_engine, get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    researcher = ContactResearcher(session)
    info = researcher.check_profile_viewers()

    console.print(f"\n[bold]Profile Viewers URL:[/bold] {info['viewers_url']}")
    console.print(f"\n[bold]Instructions:[/bold]\n{info['instructions']}")
    console.print("\n[bold]To record a viewer as a contact:[/bold]")
    console.print("  outreach record-contact <company> <name> <title> [--degree N] [--open-profile]")
    session.close()


@app.command(name="update-contact-score")
def update_contact_score(
    contact: str = typer.Argument(..., help="Contact name"),
    company: str = typer.Argument(..., help="Company name"),
    classification: str = typer.Argument(..., help="POSITIVE, NEGATIVE, NEUTRAL, REFERRAL, or AUTO_REPLY"),
):
    """Update a contact's score based on response classification."""
    from src.db.database import get_session, init_db
    from src.integrations.linkedin_research import ContactResearcher

    engine = init_db()
    session = get_session(engine)
    researcher = ContactResearcher(session)
    result = researcher.update_score_from_response(contact, company, classification.upper())

    if result:
        console.print(f"[green]Updated {contact} at {company}: score = {result.contact_score}[/green]")
    else:
        console.print(f"[red]Contact '{contact}' at '{company}' not found.[/red]")
    session.close()
