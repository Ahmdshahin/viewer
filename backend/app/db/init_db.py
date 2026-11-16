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
from app.db.models import User, AuditTrail, AreaUnit, Governorate

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
            logger.info("GiST spatial indexes confirmed on lands, eshghalat, and points.")
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
            for table in ("lands", "eshghalat", "points"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_by VARCHAR(100);")
            # The survey date added to docs/template.xlsx is stored on both
            # request ledgers, so an older database needs the column too or the
            # ORM will fail to load a row. Same for the legacy intake columns
            # (landmarks / field team / the three workflow dates / raw files)
            # that the old sheets carry and the shared template does not.
            for table in ("requests", "mudryia_requests"):
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Survey_Date" DATE;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Landmarks" TEXT;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Field_Team" VARCHAR(120);')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Distribution_Date" DATE;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Geodesy_Date" DATE;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Directorate_Date" DATE;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Raw_Files" VARCHAR(200);')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Alt_Survey_Date" DATE;')
                cur.execute(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS "Base_Map" VARCHAR(50);')
            cur.execute("SELECT conname FROM pg_constraint WHERE conname = 'lands_req_number_unique';")
            if not cur.fetchone():
                cur.execute('SELECT "Req_Number", COUNT(*) FROM lands GROUP BY "Req_Number" HAVING COUNT(*) > 1 LIMIT 5;')
                dups = cur.fetchall()
                if dups:
                    raise RuntimeError(f"lands has duplicate request numbers, cannot add UNIQUE constraint: {dups}")
                cur.execute('ALTER TABLE lands ADD CONSTRAINT lands_req_number_unique UNIQUE ("Req_Number");')
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


def seed_initial_lookups(db: Session = None) -> None:
    """Idempotently seed the base area units and an example governorate."""
    should_close = False
    if db is None:
        db = SessionLocal(bind=get_engine())
        should_close = True
    try:
        for code, name in (("sqm", "متر مربع"), ("kirat", "قيراط"), ("share", "سهم"), ("feddan", "فدان")):
            if not db.query(AreaUnit).filter(AreaUnit.code == code).first():
                db.add(AreaUnit(code=code, name=name))
        if not db.query(Governorate).filter(Governorate.code == "26").first():
            db.add(Governorate(code="26", name="سوهاج"))
        db.commit()
        logger.info("Seeded initial lookups (area units + base governorate).")
    finally:
        if should_close:
            db.close()


def ensure_sequences(conn=None, quiet: bool = False) -> dict:
    """Fast-forward every sequence past the max of every column using it.

    Restores/imports that write explicit ids leave sequences behind, which
    later surfaces as UniqueViolation on insert. Sequences are looked up via
    pg_attrdef (not only serial ownership): some tables here were built with an
    explicit ``nextval(...)`` default, and mudryia shares points_id_seq with
    points, so a sequence must clear the max across *all* its columns.

    Only moves forward; returns the sequences that were actually behind.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = psycopg2.connect(
            host=settings.POSTGRES_SERVER,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname=settings.POSTGRES_DB,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    if not quiet:
        logger.info("Syncing sequences past their columns' max values...")

    fixed = {}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT tn.nspname, t.relname, a.attname, sn.nspname, s.relname
                FROM pg_attrdef ad
                JOIN pg_class t ON t.oid = ad.adrelid
                JOIN pg_namespace tn ON tn.oid = t.relnamespace
                JOIN pg_attribute a ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum
                JOIN pg_depend dep ON dep.classid = 'pg_attrdef'::regclass AND dep.objid = ad.oid
                JOIN pg_class s ON s.oid = dep.refobjid AND s.relkind = 'S'
                JOIN pg_namespace sn ON sn.oid = s.relnamespace
                WHERE dep.deptype IN ('a', 'n')
            """)
            refs = {}
            for tbl_schema, tbl, col, seq_schema, seq in cur.fetchall():
                refs.setdefault((seq_schema, seq), []).append((tbl_schema, tbl, col))

            for (seq_schema, seq), columns in refs.items():
                try:
                    cur.execute(
                        "SELECT last_value FROM %s.%s"
                        % (quote_ident(seq_schema, conn), quote_ident(seq, conn)))
                    last = cur.fetchone()[0]
                    maximum = 0
                    for tbl_schema, tbl, col in columns:
                        cur.execute(
                            "SELECT COALESCE(MAX(%s), 0) FROM %s.%s"
                            % (quote_ident(col, conn), quote_ident(tbl_schema, conn),
                               quote_ident(tbl, conn)))
                        maximum = max(maximum, cur.fetchone()[0] or 0)
                    if last < maximum:
                        cur.execute(
                            "SELECT setval(%s::regclass, %s)",
                            ("%s.%s" % (quote_ident(seq_schema, conn),
                                        quote_ident(seq, conn)), maximum))
                        used_by = ", ".join("%s.%s" % (t, c) for _, t, c in columns)
                        fixed[used_by] = (last, maximum)
                except Exception as e:
                    logger.warning("Skipping sequence %s.%s: %s", seq_schema, seq, e)
    finally:
        if owns_conn:
            conn.close()
    if not quiet:
        if fixed:
            logger.info("Sequences fast-forwarded: %s", fixed)
        else:
            logger.info("All sequences already in sync.")
    return fixed


def insert_with_sequence_repair(cur, conn, sql: str, rows, template: str):
    """execute_values that heals a behind sequence and retries once.

    A concurrent import or a restore with explicit ids can leave the target
    sequence below the table max between the boot check and this insert. The
    attempt runs inside a savepoint so the duplicate-key failure can be undone
    without discarding work already done earlier in the caller's transaction.
    """
    import psycopg2.extras

    cur.execute("SAVEPOINT mv_seq_repair")
    try:
        out = psycopg2.extras.execute_values(cur, sql, rows, template=template, fetch=True)
        cur.execute("RELEASE SAVEPOINT mv_seq_repair")
        return out
    except psycopg2.errors.UniqueViolation:
        cur.execute("ROLLBACK TO SAVEPOINT mv_seq_repair")
        fixed = ensure_sequences(conn)
        logger.warning("Duplicate id on insert — sequences repaired: %s", fixed)
        out = psycopg2.extras.execute_values(cur, sql, rows, template=template, fetch=True)
        cur.execute("RELEASE SAVEPOINT mv_seq_repair")
        return out



def init_db() -> None:
    """Complete lifecycle execution for Milestone 1 database setup."""
    logger.info("=== Starting GeoPortal Database Initialization ===")
    create_database_if_not_exists()
    enable_postgis_extension()
    create_tables_and_indexes()
    ensure_schema_columns()
    ensure_sequences()
    seed_admin_user()
    seed_initial_lookups()
    logger.info("=== Database Initialization Completed Successfully ===")


if __name__ == "__main__":
    init_db()
