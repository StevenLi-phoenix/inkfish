"""inkfish.storage.db — SQLAlchemy engine factory, session factory, and DB init.

WAL pragma:
  SQLite's default journal mode is DELETE (rollback journal).  WAL mode gives:
  - Concurrent readers during a write (important for API + sim running side-by-side)
  - Faster writes (writers don't block readers)
  - Atomic crash recovery via the WAL log file
  PRAGMA synchronous=NORMAL is safe with WAL — full durability at each WAL
  checkpoint, with ~2–5× the write throughput of FULL.
  PRAGMA foreign_keys=ON enforces referential integrity at the SQLite level.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)


def _apply_sqlite_pragmas(dbapi_connection: Any, connection_record: object) -> None:  # noqa: ARG001
    """Apply WAL mode and related pragmas on every new SQLite connection.

    This listener fires on ``Engine.connect``.  The cursor is created and
    closed locally so the pragma is applied before any ORM work begins.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
    logger.debug("SQLite WAL pragmas applied to new connection")


def create_db_engine(db_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy Engine from *db_url*.

    For SQLite URLs (``sqlite:///...``) the WAL journal mode and supporting
    pragmas are registered via a connection-level event listener so they apply
    to every connection in the pool, including new connections after a pool
    recycle.

    Args:
        db_url: SQLAlchemy database URL.
        echo: Forward SQL statements to the Python logging framework when True.

    Returns:
        A configured :class:`sqlalchemy.engine.Engine` instance.
    """
    from sqlalchemy import create_engine  # local import keeps module-level imports lean

    engine = create_engine(db_url, echo=echo)

    if db_url.startswith("sqlite:///"):
        # Register the pragma listener only for SQLite file databases.
        # In-memory SQLite (sqlite:///:memory:) doesn't support WAL, so we
        # skip the listener there — but pragmas are harmless if applied.
        # For file DBs we DO need them, so register unconditionally for sqlite.
        event.listen(engine, "connect", _apply_sqlite_pragmas)
        logger.debug("Registered SQLite WAL pragma listener for %s", db_url)

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a :class:`~sqlalchemy.orm.sessionmaker` bound to *engine*.

    Usage::

        SessionLocal = make_session_factory(engine)
        with SessionLocal() as session:
            session.add(row)
            session.commit()
    """
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all ORM-declared tables in the target database.

    Safe to call multiple times — ``create_all`` is idempotent (uses
    ``IF NOT EXISTS`` under the hood).  This does NOT run Alembic migrations;
    Alembic is introduced in P2 when the schema stabilises.
    """
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialised via Base.metadata.create_all")
