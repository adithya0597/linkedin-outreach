from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.orm import Base


def get_engine(db_path: str = "data/outreach.db") -> Engine:
    """Create SQLite engine with WAL mode for concurrent reads."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-10000")  # 10MB cache
        cursor.execute("PRAGMA busy_timeout=5000")  # 5 second busy timeout
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()

    @event.listens_for(engine, "close")
    def optimize_on_close(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA optimize")
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create all tables."""
    Base.metadata.create_all(engine)


def get_session(engine: Engine) -> Session:
    """Create a new session."""
    session_factory = sessionmaker(bind=engine)
    return session_factory()
