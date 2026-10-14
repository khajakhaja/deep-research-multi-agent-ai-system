"""Database engine and session management.

Supports SQLite for zero-config local development and PostgreSQL for
production. Connections are never shared across threads unsafely: SQLite is
opened with ``check_same_thread=False`` and a fresh session is created per
unit of work.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _ensure_sqlite_directory(database_url: str) -> None:
    """Create the parent directory for a file-backed SQLite database."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    path_part = database_url[len(prefix):]
    if path_part in (":memory:", "") or path_part.startswith(":memory:"):
        return
    resolved = Path(path_part)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    resolved.parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(database_url: str) -> Engine:
    """Create a configured SQLAlchemy engine for ``database_url``."""
    _ensure_sqlite_directory(database_url)

    connect_args: dict = {}
    engine_kwargs: dict = {"future": True, "pool_pre_ping": True}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args

    engine = create_engine(database_url, **engine_kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def init_engine(database_url: Optional[str] = None) -> Engine:
    """Initialise the global engine (idempotent)."""
    global _engine, _SessionLocal
    if _engine is not None and database_url is None:
        return _engine

    if database_url is None:
        from app.config import get_settings

        database_url = get_settings().database_url

    _engine = create_db_engine(database_url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def init_db() -> None:
    """Create all tables if they do not exist."""
    from app.database import models  # noqa: F401  (register models)

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised at %s", engine.url.render_as_string(hide_password=True))


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> str:
    """Return 'ok' if the database answers a trivial query, else 'error'."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # pragma: no cover - depends on live DB
        logger.warning("Database health check failed: %s", exc)
        return "error"
