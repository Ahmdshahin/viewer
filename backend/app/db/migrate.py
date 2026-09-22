"""Unified Database GPKG to PostGIS Migration Engine.
Migrates all 152 Land parcels, 71 Eshghalat occupations, and 973 Points from Unified_Database.gpkg
into PostgreSQL / PostGIS with EPSG:32636 planar area recalculation, 4200.8333 statutory Feddan conversion,
2D geometry normalization, ST_MakeValid repair with ST_CollectionExtract, interior ST_PointOnSurface extraction,
and audit logging.
"""

import json
import logging
import os
import sys
from typing import Optional

# Ensure backend root is on sys.path for direct script execution
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_current_dir, "..", ".."))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import geopandas as gpd
import psycopg2
import psycopg2.extras
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("migrate")


def get_db_connection():
    """Establish and return a psycopg2 connection to the geoportal database."""
    return psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )


def get_admin_user_id(conn) -> Optional[int]:
    """Retrieve the user ID of the admin user for audit trail foreign-key attribution."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = 'admin' LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else None


def migrate_polygons(conn, gpkg_path: str, layer_name: str, target_table: str) -> int:
    """
    Migrate Land or Eshghalat polygons from GPKG into PostGIS.
    Performs 2D forcing, ST_MakeValid repair, ST_CollectionExtract(3) polygonal filtering,
    MultiPolygon normalization, EPSG:32636 area calculation, 4200.8333 Feddan conversion,
    and ST_PointOnSurface interior reference coordinate extraction.
    """
    logger.info("Reading layer '%s' from %s...", layer_name, gpkg_path)
    gdf = gpd.read_file(gpkg_path, layer=layer_name)
    feature_count = len(gdf)
    logger.info("Read %d features from '%s'. Preparing SQL batch records...", feature_count, layer_name)

    records = [
        (
            str(row["Req_Number"]).strip() if row.get("Req_Number") is not None else None,
            str(row["Owner_Name"]).strip() if row.get("Owner_Name") is not None else None,
            str(row["Layer_Type"]).strip() if row.get("Layer_Type") is not None else layer_name,
            row.geometry.wkt,
        )
        for _, row in gdf.iterrows()
    ]

    insert_sql = f"""
        INSERT INTO {target_table} (
            req_number, owner_name, layer_type, area_sqm, area_feddan, x, y, geom
        )
        SELECT
            v.req_number,
            v.owner_name,
            v.layer_type,
            ROUND(ST_Area(g.geom)::numeric, 2) AS area_sqm,
            ROUND((ST_Area(g.geom) / {settings.FEDDAN_CONSTANT})::numeric, 4) AS area_feddan,
            ST_X(ST_PointOnSurface(g.geom)) AS x,
            ST_Y(ST_PointOnSurface(g.geom)) AS y,
            g.geom
        FROM (VALUES %s) AS v(req_number, owner_name, layer_type, wkt)
        CROSS JOIN LATERAL (
            SELECT ST_Multi(
                ST_CollectionExtract(
                    ST_MakeValid(
                        ST_Force2D(
                            ST_GeomFromText(v.wkt, 32636)
                        )
                    ),
                    3
                )
            ) AS geom
        ) g;
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, records, template="(%s, %s, %s, %s)")
    conn.commit()
    logger.info("Successfully migrated %d features into '%s'.", len(records), target_table)
    return len(records)


def migrate_points(conn, gpkg_path: str, layer_name: str = "Point", target_table: str = "points") -> int:
    """
    Migrate survey points from GPKG into PostGIS.
    Performs 2D forcing (ST_Force2D) and direct ST_X / ST_Y coordinate extraction.
    """
    logger.info("Reading layer '%s' from %s...", layer_name, gpkg_path)
    gdf = gpd.read_file(gpkg_path, layer=layer_name)
    feature_count = len(gdf)
    logger.info("Read %d features from '%s'. Preparing SQL batch records...", feature_count, layer_name)

    records = [
        (
            str(row["Req_Number"]).strip() if row.get("Req_Number") is not None else None,
            str(row["Owner_Name"]).strip() if row.get("Owner_Name") is not None else None,
            str(row["Layer_Type"]).strip() if row.get("Layer_Type") is not None else layer_name,
            row.geometry.wkt,
        )
        for _, row in gdf.iterrows()
    ]

    insert_sql = f"""
        INSERT INTO {target_table} (
            req_number, owner_name, layer_type, x, y, geom
        )
        SELECT
            v.req_number,
            v.owner_name,
            v.layer_type,
            ST_X(g.geom) AS x,
            ST_Y(g.geom) AS y,
            g.geom
        FROM (VALUES %s) AS v(req_number, owner_name, layer_type, wkt)
        CROSS JOIN LATERAL (
            SELECT ST_Force2D(ST_GeomFromText(v.wkt, 32636)) AS geom
        ) g;
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, records, template="(%s, %s, %s, %s)")
    conn.commit()
    logger.info("Successfully migrated %d features into '%s'.", len(records), target_table)
    return len(records)


def log_migration_audit_entry(
    conn,
    table_name: str,
    layer_name: str,
    feature_count: int,
    gpkg_path: str,
    user_id: Optional[int] = None,
    username: str = "admin",
) -> None:
    """Record a migration event in the audit_trail table."""
    audit_sql = """
        INSERT INTO audit_trail (
            table_name, record_id, action, old_values, new_values, user_id, username, created_at, timestamp
        ) VALUES (
            %s, NULL, 'MIGRATE', NULL, %s, %s, %s, NOW(), NOW()
        );
    """
    metadata = {
        "source_file": os.path.basename(gpkg_path),
        "source_layer": layer_name,
        "features_migrated": feature_count,
        "crs_source": "EPSG:32636",
        "crs_target": "EPSG:32636",
        "geometry_type": "MultiPolygon" if layer_name in ("Land", "Eshghalat") else "Point",
        "status": "completed",
        "area_recalculated": layer_name in ("Land", "Eshghalat"),
        "feddan_conversion_factor": settings.FEDDAN_CONSTANT if layer_name in ("Land", "Eshghalat") else None,
    }

    with conn.cursor() as cur:
        cur.execute(
            audit_sql,
            (
                table_name,
                json.dumps(metadata, ensure_ascii=False),
                user_id,
                username,
            ),
        )
    conn.commit()
    logger.info("Logged audit record for table '%s' (features: %d).", table_name, feature_count)


def run_migration(gpkg_path: str = None, truncate: bool = True) -> dict:
    """
    Main migration controller:
    Reads Unified_Database.gpkg and migrates Land (152), Eshghalat (71), and Point (973)
    into PostGIS with full geometry normalization and audit logging.
    """
    if gpkg_path is None:
        gpkg_path = settings.DEFAULT_GPKG_PATH

    if not os.path.exists(gpkg_path):
        raise FileNotFoundError(f"Unified Database GPKG not found at: {gpkg_path}")

    logger.info("=== Starting Unified Database GPKG Migration ===")
    logger.info("Source GPKG: %s", gpkg_path)

    conn = get_db_connection()
    try:
        admin_id = get_admin_user_id(conn)
        admin_username = "admin" if admin_id else "system"

        if truncate:
            logger.info("Truncating existing cadastral tables and prior migration audit records...")
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE land_parcels, eshghalat, points RESTART IDENTITY CASCADE;")
                cur.execute("DELETE FROM audit_trail WHERE action = 'MIGRATE';")
            conn.commit()

        # 1. Migrate Land layer (152 features)
        land_count = migrate_polygons(conn, gpkg_path, "Land", "land_parcels")
        log_migration_audit_entry(conn, "land_parcels", "Land", land_count, gpkg_path, admin_id, admin_username)

        # 2. Migrate Eshghalat layer (71 features)
        esh_count = migrate_polygons(conn, gpkg_path, "Eshghalat", "eshghalat")
        log_migration_audit_entry(conn, "eshghalat", "Eshghalat", esh_count, gpkg_path, admin_id, admin_username)

        # 3. Migrate Point layer (973 features)
        pt_count = migrate_points(conn, gpkg_path, "Point", "points")
        log_migration_audit_entry(conn, "points", "Point", pt_count, gpkg_path, admin_id, admin_username)

        summary = {
            "land_parcels": land_count,
            "eshghalat": esh_count,
            "points": pt_count,
            "status": "success",
        }
        logger.info("=== Migration Completed Successfully: %s ===", summary)
        return summary
    finally:
        conn.close()


if __name__ == "__main__":
    target_gpkg = sys.argv[1] if len(sys.argv) > 1 else settings.DEFAULT_GPKG_PATH
    run_migration(target_gpkg)
