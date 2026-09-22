"""SQLAlchemy database engine and session factory configuration."""

from typing import Generator
import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

# Engine is built lazily so the admin can switch the Postgres connection at
# runtime (db_connection.json override); sessions always bind the current one.
_engine = None
_engine_url = None


def get_engine():
    """Return the current engine, rebuilding it when the connection changed."""
    global _engine, _engine_url
    url = settings.DATABASE_URL
    if _engine is None or _engine_url != url:
        if _engine is not None:
            try:
                _engine.dispose()
            except Exception:
                pass
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        _engine_url = url
    return _engine


def reset_engine():
    """Drop the cached engine so the next session uses fresh settings."""
    global _engine, _engine_url
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _engine_url = None


# Session factory (unbound); sessions bind the current engine via get_db().
SessionLocal = sessionmaker(autocommit=False, autoflush=False)

# Declarative base class for ORM models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it on exit."""
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()


def get_raw_connection():
    """Return a raw psycopg2 connection to the geoportal database."""
    return psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
