"""GPKG (file database) -> PostGIS migration API.

Moves processed features from Unified_Database.gpkg into the live PostGIS
tables (land / eshghalat / point, EPSG:4326) that the map reads, with:
- per-request-number duplicate guard (already-migrated requests are skipped),
- per-user audit_trail entries (action='MIGRATE') so every user's work is trackable.
"""

import json
import os
from typing import Dict, List, Optional

import geopandas as gpd
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.api.deps import get_current_active_editor
from app.db.models import User

router = APIRouter()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# (gpkg layer, postgis table, kind)
LAYER_MAP = [
    ("Land", "lands", "land", "land"),
    ("Eshghalat", "eshghalat", "esh", "eshghalat"),
    ("Point", "points", "point", "point"),
]

# NOTE: land/eshghalat columns are declared Polygon (not MultiPolygon) and
# point is declared Point, so multi-part geometries are dumped into one
# single-part row per part to match the column types exactly.
# Storage CRS is EPSG:32636 (matches the geometry columns); the map layer
# endpoints reproject to EPSG:4326 on output, so the viewer is unaffected.
ESH_SQL = """
    INSERT INTO {table} ("Req_Number", "Owner_Name", "Layer_Type", "created_by", "Area_SQM", "Area_Feddan", "X", "Y", geometry)
    SELECT
        v.req_number,
        v.owner_name,
        v.layer_type,
        v.migrated_by,
        ROUND(ST_Area(d.geom)::numeric, 2) AS area_sqm,
        ROUND((ST_Area(d.geom) / %(feddan)s)::numeric, 4) AS area_feddan,
        ST_X(ST_PointOnSurface(d.geom)) AS x,
        ST_Y(ST_PointOnSurface(d.geom)) AS y,
        d.geom
    FROM (VALUES %s) AS v(req_number, owner_name, layer_type, wkt, migrated_by)
    CROSS JOIN LATERAL (
        SELECT (ST_Dump(
            ST_CollectionExtract(
                ST_MakeValid(
                    ST_Force2D(
                        ST_GeomFromText(v.wkt, 32636)
                    )
                ),
                3
            )
        )).geom AS geom
    ) d
    WHERE ST_Area(d.geom) > 0.01
    RETURNING id;
"""

# Land holds exactly ONE row per request (the largest part); a UNIQUE
# constraint on Req_Number enforces this at the database level too.
LAND_SQL = """
    INSERT INTO {table} ("Req_Number", "Owner_Name", "Layer_Type", "created_by", "Area_SQM", "Area_Feddan", "X", "Y", geometry)
    SELECT DISTINCT ON (v.req_number)
        v.req_number,
        v.owner_name,
        v.layer_type,
        v.migrated_by,
        ROUND(ST_Area(d.geom)::numeric, 2) AS area_sqm,
        ROUND((ST_Area(d.geom) / %(feddan)s)::numeric, 4) AS area_feddan,
        ST_X(ST_PointOnSurface(d.geom)) AS x,
        ST_Y(ST_PointOnSurface(d.geom)) AS y,
        d.geom
    FROM (VALUES %s) AS v(req_number, owner_name, layer_type, wkt, migrated_by)
    CROSS JOIN LATERAL (
        SELECT (ST_Dump(
            ST_CollectionExtract(
                ST_MakeValid(
                    ST_Force2D(
                        ST_GeomFromText(v.wkt, 32636)
                    )
                ),
                3
            )
        )).geom AS geom
    ) d
    WHERE ST_Area(d.geom) > 0.01
    ORDER BY v.req_number, ST_Area(d.geom) DESC
    RETURNING id;
"""

POINT_SQL = """
    INSERT INTO {table} ("Req_Number", "Owner_Name", "Layer_Type", "created_by", "X", "Y", geometry)
    SELECT
        v.req_number,
        v.owner_name,
        v.layer_type,
        v.migrated_by,
        ST_X(g.geom) AS x,
        ST_Y(g.geom) AS y,
        g.geom
    FROM (VALUES %s) AS v(req_number, owner_name, layer_type, wkt, migrated_by)
    CROSS JOIN LATERAL (
        SELECT (ST_Dump(
            ST_CollectionExtract(
                ST_Force2D(ST_GeomFromText(v.wkt, 32636)),
                1
            )
        )).geom AS geom
    ) g
    RETURNING id;
"""


class MigrateRunRequest(BaseModel):
    output_gpkg: Optional[str] = None


def _connect():
    return psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )


def _gpkg_layers(gpkg_path: str) -> List[str]:
    import pyogrio
    try:
        info = pyogrio.list_layers(gpkg_path)
        if hasattr(info, "columns") and "name" in info.columns:
            return info["name"].tolist()
        return [row[0] for row in info]
    except Exception:
        return []


def _table_counts(cur, tables: List[str]) -> Dict[str, int]:
    counts = {}
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t};")
            counts[t] = int(cur.fetchone()[0])
        except Exception:
            counts[t] = -1
    return counts


@router.get("/status")
def migrate_status(output_gpkg: Optional[str] = Query(None)):
    """Show what is available to migrate (GPKG) vs what is already live (PostGIS)."""
    gpkg = output_gpkg if output_gpkg else os.path.join(BASE_DIR, "Unified_Database.gpkg")
    result: Dict = {"gpkg_path": gpkg, "gpkg_exists": os.path.exists(gpkg),
                    "gpkg_layers": {}, "postgis": {}}
    if os.path.exists(gpkg):
        for gp_layer, _, _, _ in LAYER_MAP:
            try:
                import pyogrio
                meta = pyogrio.read_info(gpkg, layer=gp_layer)
                result["gpkg_layers"][gp_layer] = int(meta.get("features", meta.get("feature_count", 0)))
            except Exception:
                result["gpkg_layers"][gp_layer] = 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            raw = _table_counts(cur, ["lands", "eshghalat", "points"])
            # Frontend contract uses the short keys
            result["postgis"] = {"land": raw.get("lands", 0),
                                 "eshghalat": raw.get("eshghalat", 0),
                                 "point": raw.get("points", 0)}
    finally:
        conn.close()
    return result


@router.get("/history")
def migrate_history(limit: int = Query(50, ge=1, le=200)):
    """Recent migrations with the user who ran each one (newest first)."""
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, table_name, action, user_id, username, created_at, new_values
                   FROM audit_trail WHERE action = 'MIGRATE'
                   ORDER BY id DESC LIMIT %s;""",
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    history = []
    for r in rows:
        meta = r.get("new_values") or {}
        history.append({
            "id": r["id"],
            "table": r["table_name"],
            "username": r["username"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "migrated": meta.get("features_migrated", 0),
            "skipped": meta.get("requests_skipped", 0),
        })
    return {"history": history}


@router.post("/run")
def migrate_run(request: MigrateRunRequest, current_user: User = Depends(get_current_active_editor)):
    """Migrate GPKG layers into PostGIS, skipping already-migrated request numbers.

    Only users with admin/editor role may run this; every layer migrated is
    recorded in audit_trail under the calling user's name.
    """
    gpkg = request.output_gpkg if request.output_gpkg else os.path.join(BASE_DIR, "Unified_Database.gpkg")
    if not os.path.exists(gpkg):
        raise HTTPException(status_code=400, detail=f"Database file not found: {gpkg}. Run the pipeline first.")

    migrated: Dict[str, int] = {}
    skipped: Dict[str, int] = {}
    skipped_reqs: Dict[str, List[str]] = {}
    orphaned: Dict[str, int] = {}
    orphaned_reqs: Dict[str, List[str]] = {}
    audit_ids: Dict[str, int] = {}
    land_present = None

    conn = _connect()
    try:
        with conn.cursor() as cur:
            for gp_layer, table, kind, rkey in LAYER_MAP:
                try:
                    gdf = gpd.read_file(gpkg, layer=gp_layer, engine="pyogrio")
                except Exception:
                    migrated[rkey] = 0
                    skipped[rkey] = 0
                    skipped_reqs[rkey] = []
                    continue

                if gdf is None or gdf.empty:
                    migrated[rkey] = 0
                    skipped[rkey] = 0
                    skipped_reqs[rkey] = []
                    continue

                # Normalize everything to EPSG:32636 planar meters for area + transform math
                try:
                    if gdf.crs is None:
                        gdf = gdf.set_crs(epsg=32636)
                    elif gdf.crs.to_epsg() != 32636:
                        gdf = gdf.to_crs(epsg=32636)
                except Exception:
                    pass
                gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
                if gdf.empty:
                    migrated[rkey] = 0
                    skipped[rkey] = 0
                    skipped_reqs[rkey] = []
                    continue

                cur.execute(f'SELECT DISTINCT "Req_Number" FROM {table};')
                existing = {r[0] for r in cur.fetchall() if r[0]}

                records = []
                skipped_here = []
                for _, row in gdf.iterrows():
                    req = str(row["Req_Number"]).strip() if row.get("Req_Number") is not None else None
                    if req and req in existing:
                        skipped_here.append(req)
                        continue
                    owner = str(row["Owner_Name"]).strip() if row.get("Owner_Name") is not None else None
                    ltype = str(row["Layer_Type"]).strip() if row.get("Layer_Type") is not None else gp_layer
                    records.append((req, owner, ltype, row.geometry.wkt, current_user.username))

                # Eshghalat/Point rows must belong to a Land row (same request):
                # drop rows whose request has no land parcel.
                orphaned_here = []
                if kind in ("esh", "point") and land_present is not None:
                    kept = []
                    for rec in records:
                        if rec[0] and rec[0] not in land_present:
                            orphaned_here.append(rec[0])
                        else:
                            kept.append(rec)
                    records = kept

                if records:
                    if kind == "land":
                        sql = LAND_SQL.format(table=table)
                    elif kind == "esh":
                        sql = ESH_SQL.format(table=table)
                    else:
                        sql = POINT_SQL.format(table=table)
                    if kind in ("land", "esh"):
                        # inject feddan constant (execute_values handles only the VALUES template)
                        sql = sql.replace("%(feddan)s", str(settings.FEDDAN_CONSTANT))
                    # RETURNING gives actual inserted rows (dumped parts expand one input row into many)
                    inserted = psycopg2.extras.execute_values(cur, sql, records, template="(%s, %s, %s, %s, %s)", fetch=True)
                    migrated[rkey] = len(inserted) if inserted is not None else 0
                else:
                    migrated[rkey] = 0
                if kind == "land":
                    cur.execute(f'SELECT DISTINCT "Req_Number" FROM {table};')
                    land_present = {r[0] for r in cur.fetchall() if r[0]}
                # unique skipped request numbers, stable order
                seen = set()
                uniq_skipped = [r for r in skipped_here if not (r in seen or seen.add(r))]
                skipped[rkey] = len(uniq_skipped)
                skipped_reqs[rkey] = uniq_skipped[:500]
                seen_o = set()
                uniq_orphaned = [r for r in orphaned_here if not (r in seen_o or seen_o.add(r))]
                orphaned[rkey] = len(uniq_orphaned)
                orphaned_reqs[rkey] = uniq_orphaned[:500]

                meta = {
                    "source_file": os.path.basename(gpkg),
                    "source_layer": gp_layer,
                    "features_migrated": migrated[rkey],
                    "requests_skipped": len(uniq_skipped),
                    "requests_orphaned": len(uniq_orphaned),
                    "crs_source": "EPSG:32636",
                    "crs_target": "EPSG:32636",
                    "status": "completed",
                }
                cur.execute(
                    """INSERT INTO audit_trail
                       (table_name, record_id, action, old_values, new_values, user_id, username, created_at, timestamp)
                       VALUES (%s, NULL, 'MIGRATE', NULL, %s, %s, %s, NOW(), NOW()) RETURNING id;""",
                    (table, json.dumps(meta, ensure_ascii=False), current_user.id, current_user.username),
                )
                audit_ids[table] = cur.fetchone()[0]
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Migration failed: {e!r}")
    finally:
        conn.close()

    return {"migrated": migrated, "skipped": skipped,
            "skipped_requests": skipped_reqs, "orphaned": orphaned,
            "orphaned_requests": orphaned_reqs, "audit_ids": audit_ids,
            "migrated_by": current_user.username}
