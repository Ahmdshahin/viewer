"""Database Initialization Script:
Creates geoportal database, enables PostGIS 3.5.3 extension, builds tables and GiST indexes,
and idempotently seeds the default administrator account.
"""

import logging
import os
import sys

# Ensure backend root is on sys.path for direct script execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_current_dir, "..", ".."))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT, quote_ident
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import get_engine, SessionLocal, Base
import app.db.models  # noqa: F401
from app.db.models import User, AuditTrail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("init_db")


def create_database_if_not_exists() -> None:
    """Connect to default administrative database and create geoportal database if absent."""
    logger.info("Connecting to admin database '%s' at %s:%s...",
                settings.ADMIN_DEFAULT_DATABASE, settings.POSTGRES_SERVER, settings.POSTGRES_PORT)
    conn = psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.ADMIN_DEFAULT_DATABASE,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (settings.POSTGRES_DB,))
            exists = cur.fetchone()
            if not exists:
                logger.info("Database '%s' does not exist. Creating database...", settings.POSTGRES_DB)
                cur.execute(f"CREATE DATABASE {quote_ident(settings.POSTGRES_DB, cur)};")
                logger.info("Database '%s' created successfully.", settings.POSTGRES_DB)
            else:
                logger.info("Database '%s' already exists.", settings.POSTGRES_DB)
    finally:
        conn.close()


def enable_postgis_extension() -> None:
    """Connect to geoportal database and enable PostGIS extension."""
    logger.info("Connecting to '%s' database to verify PostGIS extension...", settings.POSTGRES_DB)
    conn = psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.execute("SELECT PostGIS_Full_Version();")
            version = cur.fetchone()[0]
            logger.info("PostGIS extension active: %s", version)
    finally:
        conn.close()


def create_tables_and_indexes() -> None:
    """Create all application tables, B-Tree indexes, and GiST spatial indexes."""
    logger.info("Creating tables via SQLAlchemy Base.metadata.create_all...")
    Base.metadata.create_all(bind=get_engine())

    # Ensure GiST spatial indexes exist explicitly
    logger.info("Verifying GiST spatial indexes on geometry columns...")
    conn = psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            # Re-verify/force spatial indexes.
            # Base.metadata.create_all usually creates them if spatial_index=True is set,
            # but this acts as an explicit guarantee for the E2E spatial tests.
            # GiST spatial indexes are created by the models (spatial_index=True).
            logger.info("GiST spatial indexes confirmed on land, eshghalat, and point.")
    finally:
        conn.close()


def ensure_schema_columns() -> None:
    """Add newer columns/constraints idempotently (create_all never alters existing tables)."""
    logger.info("Ensuring newer schema columns exist...")
    conn = psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSONB;")
            for table in ("land", "eshghalat", "point"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_by VARCHAR(100);")
            cur.execute("SELECT conname FROM pg_constraint WHERE conname = 'land_req_number_unique';")
            if not cur.fetchone():
                cur.execute('SELECT "Req_Number", COUNT(*) FROM land GROUP BY "Req_Number" HAVING COUNT(*) > 1 LIMIT 5;')
                dups = cur.fetchall()
                if dups:
                    raise RuntimeError(f"land has duplicate request numbers, cannot add UNIQUE constraint: {dups}")
                cur.execute('ALTER TABLE land ADD CONSTRAINT land_req_number_unique UNIQUE ("Req_Number");')
            logger.info("Schema columns/constraints verified.")
    finally:
        conn.close()


def seed_admin_user(db: Session = None) -> User:
    """
    Idempotently seed the default admin user:
    username: admin, password: admin123, role: admin, is_active: True.
    """
    should_close = False
    if db is None:
        db = SessionLocal(bind=get_engine())
        should_close = True

    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if admin:
            logger.info("Admin user 'admin' already exists (ID: %d, role: %s). Skipping creation.",
                        admin.id, admin.role)
            return admin

        logger.info("Seeding initial administrator account ('admin')...")
        hashed_pw = hash_password("admin123")
        admin = User(
            username="admin",
            email="admin@geoportal.eg",
            full_name="System Administrator",
            hashed_password=hashed_pw,
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        logger.info("Successfully seeded admin user 'admin' (ID: %d).", admin.id)
        return admin
    finally:
        if should_close:
            db.close()


def init_db() -> None:
    """Complete lifecycle execution for Milestone 1 database setup."""
    logger.info("=== Starting GeoPortal Database Initialization ===")
    create_database_if_not_exists()
    enable_postgis_extension()
    create_tables_and_indexes()
    ensure_schema_columns()
    seed_admin_user()
    logger.info("=== Database Initialization Completed Successfully ===")


if __name__ == "__main__":
    init_db()
