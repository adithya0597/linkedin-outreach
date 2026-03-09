"""Shared DB session context manager for CLI commands."""

from contextlib import contextmanager


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
