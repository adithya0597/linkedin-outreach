"""Validation-related CLI commands: validate, score, score-all, h1b, enrich-h1b, domain-match."""

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command()
def validate(
    company: str = typer.Argument(help="Company name to validate"),
):
    """Validate a company against target criteria."""
    from src.validators.company_validator import CompanyValidator

    validator = CompanyValidator()
    result = validator.validate_by_name(company)
    console.print(result)


@app.command()
def score(
    company: str = typer.Argument(help="Company name to score"),
    semantic: bool = typer.Option(False, help="Include semantic embedding scores"),
):
    """Calculate deterministic fit score for a company."""
    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.validators.scoring_engine import FitScoringEngine

    engine = get_engine()
    session = get_session(engine)
    comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
    if not comp:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        return

    scorer = FitScoringEngine()
    breakdown = scorer.score(comp, include_semantic=semantic)

    table = Table(title=f"Fit Score: {comp.name}")
    table.add_column("Component", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")
    table.add_row("H1B Status", f"{breakdown.h1b_score}", "15")
    table.add_row("Company Criteria", f"{breakdown.criteria_score}", "15")
    table.add_row("Tech Overlap", f"{breakdown.tech_overlap_score}", "10")
    table.add_row("Salary Alignment", f"{breakdown.salary_score}", "10")
    table.add_row("[bold]Deterministic Total[/bold]", f"[bold]{breakdown.deterministic_total}[/bold]", "50")
    if semantic:
        table.add_row("Profile-JD Similarity", f"{breakdown.profile_jd_similarity}", "25")
        table.add_row("Domain-Company Similarity", f"{breakdown.domain_company_similarity}", "25")
        table.add_row("[bold]Semantic Total[/bold]", f"[bold]{breakdown.semantic_total}[/bold]", "50")
    table.add_row("[bold green]TOTAL[/bold green]", f"[bold green]{breakdown.total}[/bold green]", "100" if semantic else "50")
    console.print(table)
    session.close()


@app.command(name="score-all")
def score_all(
    semantic: bool = typer.Option(False, help="Include semantic + domain match scoring"),
    limit: int = typer.Option(None, help="Limit to top N results displayed"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip Notion sync after scoring"),
):
    """Re-score all companies with optional domain match bonus."""
    from src.db.database import get_engine, get_session, init_db
    from src.pipeline.orchestrator import Pipeline

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    pipeline = Pipeline(session)
    results = pipeline.score_all(include_semantic=semantic)

    console.print(f"[bold]Scored {results['scored']} companies[/bold]")

    top = results["top_10"]
    if limit:
        top = top[:limit]

    table = Table(title="Top Companies by Fit Score")
    table.add_column("#", justify="right")
    table.add_column("Company", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Tier")
    for i, (name, score_val, tier_val) in enumerate(top, 1):
        table.add_row(str(i), name, f"{score_val}", tier_val)
    console.print(table)

    if not no_sync:
        from src.cli._db import auto_sync
        auto_sync(session)

    session.close()


@app.command()
def h1b(
    company: str = typer.Argument(help="Company name to verify H1B status"),
    batch: bool = typer.Option(False, help="Verify all unverified companies"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip Notion sync after verification"),
):
    """Verify H1B sponsorship status via 3-source waterfall."""
    import asyncio

    from src.db.database import get_engine, get_session
    from src.db.orm import CompanyORM
    from src.validators.h1b_verifier import H1BVerifier

    engine = get_engine()
    session = get_session(engine)
    verifier = H1BVerifier()

    if batch:
        companies = session.query(CompanyORM).filter(
            CompanyORM.h1b_status.in_(["Unknown", "", None]),
            CompanyORM.is_disqualified == False,  # noqa: E712
        ).all()
        console.print(f"[bold]Batch verifying {len(companies)} companies...[/bold]")
        results = asyncio.run(verifier.batch_verify(companies, session=session))
        table = Table(title="H1B Verification Results")
        table.add_column("Company", style="bold")
        table.add_column("Status")
        table.add_column("Source")
        for record in results:
            style = {"Confirmed": "green", "Explicit No": "red"}.get(record.status.value, "yellow")
            table.add_row(record.company_name, f"[{style}]{record.status.value}[/{style}]", record.source)
        console.print(table)
    else:
        comp = session.query(CompanyORM).filter(CompanyORM.name.ilike(f"%{company}%")).first()
        if not comp:
            console.print(f"[red]Company '{company}' not found in database.[/red]")
            session.close()
            return
        console.print(f"[bold]Verifying H1B for {comp.name}...[/bold]")
        record = asyncio.run(verifier.verify(comp))

        table = Table(title=f"H1B: {comp.name}")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        style = {"Confirmed": "green", "Explicit No": "red"}.get(record.status.value, "yellow")
        table.add_row("Status", f"[{style}]{record.status.value}[/{style}]")
        table.add_row("Source", record.source)
        if record.lca_count:
            table.add_row("LCA Count", str(record.lca_count))
        if record.approval_rate is not None:
            table.add_row("Approval Rate", f"{record.approval_rate}%")
        if record.has_perm:
            table.add_row("PERM", "Yes")
        if record.has_everify:
            table.add_row("E-Verify", "Yes")
        console.print(table)

    if not no_sync:
        from src.cli._db import auto_sync
        auto_sync(session)

    session.close()


@app.command(name="enrich-h1b")
def enrich_h1b(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show matches without updating"),
    no_sync: bool = typer.Option(False, "--no-sync", help="Skip Notion sync after enrichment"),
):
    """Apply known H1B statuses from Frog Hire lookup to Unknown companies."""
    from src.db.database import get_engine, get_session, init_db
    from src.db.h1b_lookup import KNOWN_H1B_STATUSES, apply_known_statuses
    from src.db.orm import CompanyORM

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)

    if dry_run:
        unknown = session.query(CompanyORM).filter(
            CompanyORM.h1b_status == "Unknown"
        ).all()
        table = Table(title="H1B Enrichment Preview (dry run)")
        table.add_column("Company", style="bold")
        table.add_column("Current")
        table.add_column("Known Status")
        matches = 0
        for comp in unknown:
            for known_name, status in KNOWN_H1B_STATUSES.items():
                if comp.name.lower() == known_name.lower() and status != "Unknown":
                    table.add_row(comp.name, comp.h1b_status, f"[green]{status}[/green]")
                    matches += 1
                    break
        console.print(table)
        console.print(f"\n[bold]{matches} companies would be updated.[/bold]")
    else:
        count = apply_known_statuses(session)
        console.print(f"[green]Updated {count} companies with known H1B statuses.[/green]")
        if not no_sync:
            from src.cli._db import auto_sync
            auto_sync(session)

    session.close()


@app.command(name="domain-match")
def domain_match(
    company: str = typer.Argument(..., help="Company name to match domain"),
):
    """Show which experience domain best matches a company."""
    from src.db.database import get_session, init_db
    from src.db.orm import CompanyORM
    from src.outreach.personalizer import EXPERIENCE_MAP, OutreachPersonalizer

    engine = init_db()
    session = get_session(engine)
    personalizer = OutreachPersonalizer()

    company_orm = session.query(CompanyORM).filter(CompanyORM.name.ilike(company)).first()
    if not company_orm:
        console.print(f"[red]Company '{company}' not found in database.[/red]")
        session.close()
        return

    domain = personalizer._match_domain(company_orm)
    exp = EXPERIENCE_MAP[domain]
    console.print(f"\n[bold]{company_orm.name}[/bold] -> Domain: [cyan]{domain}[/cyan]")
    console.print(f"  Experience: {exp['relevant_experience']}")
    console.print(f"  Metric: {exp['metric']}")
    console.print(f"  Value prop: {exp['value_prop']}")
    session.close()
