"""Shared DB session context manager and sync helpers for CLI commands."""

from contextlib import contextmanager

import typer


@contextmanager
def db_session():
    """Yield a SQLAlchemy session, ensuring init_db and cleanup."""
    from src.db.database import get_engine, get_session, init_db

    engine = get_engine()
    init_db(engine)
    session = get_session(engine)
    try:
        yield session
    finally:
        session.close()


def auto_sync(session, dry_run=False):
    """Run bidirectional Notion sync. Silently skips if no credentials."""
    import asyncio
    import os

    from src.integrations.notion_bidirectional import ConflictStrategy, NotionBidirectionalSync

    api_key = os.environ.get("NOTION_API_KEY", "")
    db_id = os.environ.get("NOTION_DB_ID", "") or os.environ.get(
        "NOTION_DATABASE_ID", ""
    )
    if not api_key or not db_id:
        return
    syncer = NotionBidirectionalSync(api_key, db_id, session)
    try:
        result = asyncio.run(
            syncer.full_sync(strategy=ConflictStrategy.NEWEST_WINS, dry_run=dry_run)
        )
        pushed = result.get("pushed", 0)
        pulled = result.get("pulled", 0)
        conflicts = result.get("conflicts_found", 0)
        typer.echo(
            f"  Notion sync: {pushed} pushed, {pulled} pulled, {conflicts} conflicts"
        )
    except Exception as e:
        typer.echo(f"  Notion sync failed (non-fatal): {e}", err=True)
