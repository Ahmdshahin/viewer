"""Geometry Update Tool API.

Right-side docked tool in the map viewer. Lets an editor search features for a
request number across related layers, upload replacement geometry as one ZIP of
shapefiles, and commits per-layer updates (update-in-place for a master layer,
delete-and-insert for related/child layers) with backups, audit logging, and a
time-limited undo.

Relationship configuration is data-driven (update_relationship_groups table),
not hardcoded, so new groups/layers are added without touching this module's
rule logic.
"""

import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.api import tiles
from app.core.config import settings

router = APIRouter()

# ---- constants -------------------------------------------------------------

FEDDAN_CONSTANT = settings.FEDDAN_CONSTANT  # 4200.8333 m² / feddan
DEFAULT_KEY_COLUMN = "Req_Number"
UNDO_TTL = timedelta(hours=24)

_STAGING_BASE = os.path.join(tempfile.gettempdir(), "update_geometry")
_STAGING_TTL = timedelta(hours=2)
_STAGING: dict = {}


class ColumnNotFound(Exception):
    pass


# ---- config tables ----------------------------------------------------------

_CONFIG_SQL = [
    # Relationship groups: the full config document is stored as-is (data-driven).
    """
    CREATE TABLE IF NOT EXISTS update_relationship_groups (
        id SERIAL PRIMARY KEY,
        group_key VARCHAR(100) UNIQUE NOT NULL,
        name VARCHAR(200) NOT NULL,
        config JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """,
    # Persisted per-layer classifications (update mode) chosen by the user for
    # layers that are not part of any relationship group.
    """
    CREATE TABLE IF NOT EXISTS layer_update_mode (
        layer_table VARCHAR(100) PRIMARY KEY,
        update_mode VARCHAR(50) NOT NULL,
        persist BOOLEAN NOT NULL DEFAULT FALSE,
        created_by VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """,
    # Archive of every change made by this tool (backup + undo source).
    """
    CREATE TABLE IF NOT EXISTS update_archive (
        id SERIAL PRIMARY KEY,
        action VARCHAR(50) NOT NULL,
        layer_table VARCHAR(100) NOT NULL,
        key_column VARCHAR(100) NOT NULL,
        key_value VARCHAR(300) NOT NULL,
        old_count INTEGER NOT NULL DEFAULT 0,
        new_count INTEGER NOT NULL DEFAULT 0,
        old_geojson JSONB NOT NULL DEFAULT '[]'::jsonb,
        new_geojson JSONB NOT NULL DEFAULT '[]'::jsonb,
        user_id INTEGER,
        username VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        undone_at TIMESTAMP,
        undone_by VARCHAR(100)
    );
    """,
]

DEFAULT_GROUP = {
    "group_key": "land_parcel_group",
    "name": "Land Parcel Group",
    "config": {
        "relationship_group": "land_parcel_group",
        "key_column": "Req_Number",
        "master_layer": {
            "name": "lands",
            "update_mode": "update_in_place",
            "cardinality": "one_to_one",
            "reject_if_upload_count_not_equal": 1,
        },
        "related_layers": [
            {"name": "eshghalat", "update_mode": "delete_and_insert", "inherit_attributes_from": "lands"},
            {"name": "points", "update_mode": "delete_and_insert", "inherit_attributes_from": "lands"},
        ],
    },
}


def _conn():
    return psycopg2.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )


def _ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        for sql in _CONFIG_SQL:
            cur.execute(sql)
        cur.execute("SELECT 1 FROM update_relationship_groups WHERE group_key = %s LIMIT 1;",
                    (DEFAULT_GROUP["group_key"],))
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO update_relationship_groups (group_key, name, config) VALUES (%s, %s, %s);",
                (DEFAULT_GROUP["group_key"], DEFAULT_GROUP["name"],
                 json.dumps(DEFAULT_GROUP["config"], ensure_ascii=False)),
            )
    conn.commit()


# ---- request/response models -----------------------------------------------

class QueryRequest(BaseModel):
    key_column: str = DEFAULT_KEY_COLUMN
    value: str


class UploadMapping(BaseModel):
    file_base: str
    layer_table: str


class PreviewRequest(BaseModel):
    staging_id: str
    key_column: str = DEFAULT_KEY_COLUMN
    key_value: str
    mapping: list[UploadMapping]
    # Explicit mode choices for layers with no relationship config:
    # {layer_table: "update_in_place" | "delete_and_insert"}
    modes: dict = {}
    persist_classification: dict = {}


class CommitRequest(BaseModel):
    staging_id: str
    key_column: str = DEFAULT_KEY_COLUMN
    key_value: str
    mapping: list[UploadMapping]
    modes: dict = {}
    persist_classification: dict = {}
    proceed_unresolved: bool = False


class ClassifyRequest(BaseModel):
    layer_table: str
    update_mode: str  # update_in_place | delete_and_insert
    persist: bool = True


class GroupIn(BaseModel):
    group_key: str
    name: str
    config: dict


# ---- helpers ---------------------------------------------------------------

def _q(name: str) -> str:
    return '"' + str(name).replace('"', "") + '"'


def _geom_family(gtype: str) -> str:
    g = (gtype or "").upper()
    if "POLYGON" in g or "CURVE" in g.replace("CURVEPOLYGON", ""):
        return "POLYGON"
    if "POINT" in g:
        return "POINT"
    if "LINE" in g:
        return "LINE"
    return ""


def _register_matches(db: Session, key_column: str) -> list:
    """Registered spatial layers (map_layers) that carry the key column."""
    rows = db.execute(text("""
        SELECT DISTINCT m.table_name, m.label, m.sort_order,
               g.f_geometry_column AS geom_col, g.type AS gtype, g.srid AS srid
        FROM map_layers m
        JOIN geometry_columns g ON g.f_table_name = m.table_name
        JOIN pg_class c ON c.relname = m.table_name
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        WHERE EXISTS (
            SELECT 1 FROM information_schema.columns ic
            WHERE ic.table_schema = 'public' AND ic.table_name = m.table_name
              AND ic.column_name = :k
        )
        ORDER BY m.sort_order, m.table_name
    """), {"k": key_column}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["table"] = d.pop("table_name")
        out.append(d)
    return out


def _groups(db: Session) -> list:
    rows = db.execute(text(
        "SELECT id, group_key, name, config FROM update_relationship_groups ORDER BY id"
    )).mappings().all()
    out = []
    for r in rows:
        cfg = r["config"] if isinstance(r["config"], dict) else json.loads(r["config"] or "{}")
        out.append({"id": r["id"], "group_key": r["group_key"], "name": r["name"], "config": cfg})
    return out


def _group_for_layers(configs: list, table: str):
    """Find (group_row, role, update_mode) if the layer belongs to a group."""
    for g in configs:
        cfg = g["config"]
        master = cfg.get("master_layer") or {}
        if isinstance(master, dict) and (master.get("name") == table or master.get("table") == table):
            return g, "master", master.get("update_mode", "update_in_place")
        for rel in cfg.get("related_layers") or []:
            if rel.get("name") == table or rel.get("table") == table:
                return g, "related", rel.get("update_mode", "delete_and_insert")
    return None, None, None


def _classified(db: Session) -> dict:
    rows = db.execute(text(
        "SELECT layer_table, update_mode, persist FROM layer_update_mode"
    )).mappings().all()
    return {r["layer_table"]: {"update_mode": r["update_mode"], "persist": r["persist"]} for r in rows}


def _table_count(conn, table: str, key_column: str, value: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM {_q(table)} WHERE {_q(key_column)} = %s', (value,))
        return int(cur.fetchone()[0])


def _table_bbox(conn, table: str, key_column: str, value: str):
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) FROM ("
                f"SELECT ST_Extent(ST_Transform(geometry, 4326)) AS b FROM {_q(table)} "
                f"WHERE {_q(key_column)} = %s) e",
                (value,))
            row = cur.fetchone()
            return [float(v) for v in row] if row and None not in row else None
    except Exception:
        return None


def _crs_guess(bounds):
    """Heuristic when a shapefile ships without .prj (mirrors upload.py)."""
    try:
        if max(abs(bounds[2]), abs(bounds[3])) > 180:
            return 32636
        return 4326
    except Exception:
        return 4326


def _read_shp(path: str) -> dict:
    """Read a shapefile with geopandas; return normalized feature info.

    Normalizes CRS: file CRS -> EPSG:32636 (storage CRS of all layer tables).
    """
    import geopandas as gpd
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError("shapefile contains no features")
    src_crs = getattr(gdf, "crs", None)
    bounds = gdf.total_bounds.tolist()
    if src_crs is None:
        gdf = gdf.set_crs(epsg=_crs_guess(bounds))
        crs_note = f"No CRS found; assumed EPSG:{_crs_guess(bounds)}"
    else:
        crs_note = f"CRS EPSG:{src_crs.to_epsg() if src_crs.to_epsg() else 'unknown'}"
    if gdf.crs.to_epsg() != 32636:
        gdf = gdf.to_crs(epsg=32636)
        crs_note += f" -> reprojected to EPSG:32636"
    family = set(_geom_family(g.geom_type) for g in gdf.geometry) - {""}
    return {
        "count": int(len(gdf)),
        "geom_family": (family.pop() if len(family) == 1 else "MIXED") or "",
        "crs_note": crs_note,
        "gdf": gdf,
    }


def _std_base(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _guess_layer(base: str, candidates: list, labels: dict) -> str | None:
    """Best-guess layer table for a shapefile base name (suffixes ignored)."""
    base = re.sub(r"^(.+?)(_new|_update)?$", r"\1", base) if base else base
    b = _std_base(base)
    # Strip _new/_update
    for suf in ("_new", "_update", "-new", "-update"):
        if b.endswith(_std_base(suf)):
            b = b[:-len(_std_base(suf))]
    # Singular->plural hardening for the cadastral trio
    hard = {
        "land": "lands", "parcel": "lands", "landparcel": "lands",
        "esh": "eshghalat", "eshghalat": "eshghalat",
        "point": "points", "pts": "points",
        "mudryia": "mudryia", "region": "regoin", "regoin": "regoin",
    }
    if b in hard and hard[b] in {c["table"] for c in candidates}:
        return hard[b]
    for c in candidates:
        if b == _std_base(c["table"]):
            return c["table"]
        if b == _std_base(labels.get(c["table"], "")):
            return c["table"]
    # label without spaces ("Land Parcels" -> "landparcels")
    for c in candidates:
        l = _std_base(labels.get(c["table"], ""))
        if l and b == l and len(b) > 3:
            return c["table"]
    return None


def _lineage_layers(config_groups: list) -> set:
    out = set()
    for g in config_groups:
        cfg = g["config"]
        m = cfg.get("master_layer") or {}
        out.add(m.get("name") or m.get("table"))
        for rel in cfg.get("related_layers") or []:
            out.add(rel.get("name") or rel.get("table"))
    return {x for x in out if x}


# ---- staging ---------------------------------------------------------------

def _cleanup_staging() -> None:
    now = datetime.now()
    for sid in list(_STAGING):
        if now - _STAGING[sid].get("created", now) > _STAGING_TTL:
            shutil.rmtree(_STAGING[sid]["dir"], ignore_errors=True)
            _STAGING.pop(sid, None)
    if os.path.isdir(_STAGING_BASE):
        for name in os.listdir(_STAGING_BASE):
            p = os.path.join(_STAGING_BASE, name)
            try:
                if now - datetime.fromtimestamp(os.path.getmtime(p)) > _STAGING_TTL:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass


def _new_staging() -> tuple:
    _cleanup_staging()
    sid = uuid.uuid4().hex[:16]
    d = os.path.join(_STAGING_BASE, sid)
    os.makedirs(d, exist_ok=True)
    _STAGING[sid] = {"dir": d, "created": datetime.now()}
    return sid, d


def _staging_dir(sid: str) -> str:
    e = _STAGING.get(sid)
    if not e or not os.path.isdir(e["dir"]):
        raise HTTPException(status_code=404, detail="Upload session expired or not found. Please re-upload.")
    return e["dir"]


# ---- endpoints -------------------------------------------------------------

@router.get("/config")
def get_config(db: Session = Depends(deps.get_db), current_user=Depends(deps.get_current_user)):
    conn = _conn()
    try:
        _ensure_tables(conn)
    finally:
        conn.close()
    config_groups = _groups(db)
    candidates = _register_matches(db, DEFAULT_KEY_COLUMN)
    labels = {c["table"]: c["label"] for c in candidates}
    return {
        "key_column": DEFAULT_KEY_COLUMN,
        "groups": config_groups,
        "classifications": _classified(db),
        "layers": [
            {"table": c["table"], "label": c["label"], "gtype": c["gtype"],
             "srid": int(c["srid"] or 0) or 32636}
            for c in candidates
        ],
    }


@router.post("/query")
def query(request: QueryRequest, db: Session = Depends(deps.get_db),
          current_user=Depends(deps.get_current_user)):
    value = (request.value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Search value cannot be empty")
    key = request.key_column or DEFAULT_KEY_COLUMN

    conn = _conn()
    try:
        _ensure_tables(conn)
        config_groups = _groups(db)
        candidates = [c for c in _register_matches(db, key)]
        labels = {c["table"]: c["label"] for c in candidates}

        matches = []
        for c in candidates:
            n = _table_count(conn, c["table"], key, value)
            if n <= 0:
                continue
            g, role, mode = _group_for_layers(config_groups, c["table"])
            card_violation = None
            if role == "master":
                expect = ((g["config"].get("master_layer") or {}).get("reject_if_upload_count_not_equal")
                          or 1)
                if n != expect:
                    card_violation = {"expected": expect, "found": n,
                                      "message": f"Pre-existing data issue: {c['label']} has {n} "
                                                 f"features for this request (expected exactly {expect})."}
            matches.append({
                "table": c["table"],
                "label": labels.get(c["table"], c["table"]),
                "gtype": c["gtype"],
                "count": n,
                "bbox": _table_bbox(conn, c["table"], key, value),
                "group": {"group_key": g["group_key"], "name": g["name"], "role": role} if g else None,
                "cardinality_violation": card_violation,
            })
    finally:
        conn.close()

    return {"key_column": key, "value": value, "layers": matches}


@router.post("/upload")
async def upload_zip(
    file: UploadFile = File(...),
    key_column: str = DEFAULT_KEY_COLUMN,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_user),
):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Must be a .zip file")

    sid, tmp = _new_staging()
    zip_path = os.path.join(tmp, "upload.zip")
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    if os.path.getsize(zip_path) / (1024 * 1024) > 100:
        raise HTTPException(status_code=413, detail="ZIP too large (max 100 MB)")

    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass

    conn = _conn()
    try:
        _ensure_tables(conn)
        config_groups = _groups(db)
        candidates = _register_matches(db, key_column or DEFAULT_KEY_COLUMN)
        labels = {c["table"]: c["label"] for c in candidates}
        in_lineage = _lineage_layers(config_groups)
    finally:
        conn.close()

    shps = [f for f in os.listdir(tmp) if f.lower().endswith(".shp")]
    if not shps:
        raise HTTPException(status_code=400, detail="No .shp file found in the zip")

    files = []
    for shp in sorted(shps):
        base = os.path.splitext(shp)[0]
        path = os.path.join(tmp, shp)
        try:
            info = _read_shp(path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"{base}: {str(e)}")
        layer = _guess_layer(base, candidates, labels)
        files.append({
            "file_base": base,
            "detected_layer": layer,
            "gtype": info["geom_family"],
            "count": info["count"],
            "crs_note": info["crs_note"],
            "in_lineage": layer in in_lineage,
        })
    # stage geojson copies for later preview/commit
    for f in files:
        src = os.path.join(tmp, f["file_base"] + ".shp")
        dst = os.path.join(tmp, f["file_base"] + "_staged.gpkg")
        try:
            import geopandas as gpd
            gpd.read_file(src).to_file(dst, driver="GPKG")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"{f['file_base']}: {str(e)}")

    return {"staging_id": sid, "files": files}


@router.post("/preview")
def preview(request: PreviewRequest, db: Session = Depends(deps.get_db),
            current_user=Depends(deps.get_current_user)):
    data = _preview_plan(request, db)
    return data


def _preview_plan(request: PreviewRequest, db: Session) -> dict:
    value = (request.key_value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Request number value is required")
    tmp = _staging_dir(request.staging_id)
    key = request.key_column or DEFAULT_KEY_COLUMN

    conn = _conn()
    try:
        _ensure_tables(conn)
        config_groups = _groups(db)
        classified = _classified(db)
        plan = []
        missing_related = []
        affected_groups = set()
        unresolved = []

        for m in request.mapping:
            info = tiles.resolve_table(db, m.layer_table)
            gtype = info["gtype"]
            family = _geom_family(gtype)
            staged = os.path.join(tmp, m.file_base + "_staged.gpkg")
            if not os.path.isfile(staged):
                raise HTTPException(status_code=404,
                                    detail=f"Staged file for '{m.file_base}' not found. Re-upload.")
            shp_info = _read_shp(staged)
            src_family = shp_info["geom_family"]
            count = shp_info["count"]

            g, role, mode = _group_for_layers(config_groups, m.layer_table)
            hard_reject = None
            severity = "green"
            confirm = ""
            inherit_note = ""
            mode_label = ""

            if role == "master":
                expect = ((g["config"].get("master_layer") or {}).get("reject_if_upload_count_not_equal") or 1)
                if count != expect:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Layer `{info['table']}` allows only one feature per request number. "
                               f"The uploaded file contains {count} features. Please review the file.",
                    )
                mode_label = "Update in place"
                severity = "yellow"
                confirm = (f"This will UPDATE the existing {info['table']} geometry for request "
                           f"{value} (attributes untouched).")
            elif role == "related":
                old_count = _table_count(conn, m.layer_table, key, value)
                mode_label = "Delete & insert"
                if old_count and count > old_count * 5:
                    severity = "red"
                else:
                    severity = "yellow"
                inherit_src = None
                for rel in (g["config"].get("related_layers") or []):
                    if rel.get("name") == m.layer_table:
                        inherit_src = rel.get("inherit_attributes_from")
                        break
                inherit_note = (f"Attributes inherited from `{inherit_src}` record where available."
                                if inherit_src else "")
                confirm = (f"This will delete {old_count} existing feature(s) in `{info['table']}` "
                           f"for this request and insert {count} new feature(s) instead.")
                affected_groups.add(g["group_key"])
            else:
                # unclassified layer
                mode = request.modes.get(m.layer_table)
                if not mode:
                    unresolved.append(m.layer_table)
                    mode_label = "Requires classification"
                    confirm = (f"Layer {info['table']} is not part of any relationship group. "
                               f"Choose an update mode before proceeding.")
                    severity = "yellow"
                else:
                    mode_label = "Update in place" if mode == "update_in_place" else "Delete & insert"
                    old_count = _table_count(conn, m.layer_table, key, value) if mode == "delete_and_insert" else 0
                    if mode == "delete_and_insert":
                        detail_txt = f"Will delete existing features for this request and insert {count} new feature(s)."
                    else:
                        detail_txt = "Will update this request's geometry in place."
                    confirm = f"Mode: {mode_label}. {detail_txt}"

            if family and src_family and src_family not in ("MIXED",) and family not in ("MIXED",):
                if src_family != family:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Geometry type mismatch for `{info['table']}`: file has {src_family} "
                               f"geometry but the layer stores {family}.",
                    )

            # recent history for stale/conflict warnings
            recent = []
            if role in ("related", "master"):
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT action, username, created_at, old_count, new_count, undone_at "
                        "FROM update_archive WHERE layer_table = %s AND key_column = %s AND key_value = %s "
                        "ORDER BY created_at DESC LIMIT 3",
                        (m.layer_table, key, value))
                    recent = [dict(zip(["action", "username", "created_at", "old_count", "new_count", "undone_at"], r))
                              for r in cur.fetchall()]

            plan.append({
                "layer_table": m.layer_table,
                "file_base": m.file_base,
                "role": role or "unclassified",
                "mode": mode or (role or ""),
                "mode_label": mode_label,
                "gtype": family or src_family or gtype,
                "file_gtype": src_family,
                "file_count": count,
                "old_count": _table_count(conn, m.layer_table, key, value) if role != "master" else None,
                "severity": severity,
                "confirm": confirm,
                "inherit_note": inherit_note,
                "crs_note": shp_info["crs_note"],
                "hard_reject": hard_reject,
                "recent_updates": recent,
            })

        # relationship cross-check: any group affected where DB still has matches
        # in group layers that are not included in this mapping
        if affected_groups:
            grouped = {m.layer_table for m in request.mapping}
            for gk in affected_groups:
                g = next((x for x in config_groups if x["group_key"] == gk), None)
                if not g:
                    continue
                cfg = g["config"]
                all_layers = [(cfg.get("master_layer") or {}).get("name")] + \
                             [r.get("name") for r in cfg.get("related_layers") or []]
                for lt in all_layers:
                    if not lt or lt in grouped:
                        continue
                    if _table_count(conn, lt, key, value) > 0:
                        missing_related.append(lt)

        # persistent classifications requested
        clamped = {}
        for lt, mode in request.persist_classification.items():
            if mode in ("update_in_place", "delete_and_insert"):
                clamped[lt] = mode

        return {
            "key_column": key,
            "key_value": value,
            "plan": plan,
            "missing_related": missing_related,
            "unresolved": unresolved,
            "persist_classification": clamped,
        }
    finally:
        conn.close()


@router.post("/commit")
def commit(request: CommitRequest, db: Session = Depends(deps.get_db),
           current_user=Depends(deps.get_current_active_editor)):
    data = _preview_plan(request, db)
    if data["unresolved"] and not request.modes:
        raise HTTPException(status_code=400,
                            detail="Unclassified layers require an explicit update mode.")
    if data["missing_related"] and not request.proceed_unresolved:
        raise HTTPException(
            status_code=409,
            detail="This request number also has geometry in: " + ", ".join(data["missing_related"]) +
                   ". Updating without these may break spatial alignment. Provide replacement geometry "
                   "or confirm proceeding without them.",
        )

    tmp = _staging_dir(request.staging_id)
    key = request.key_column or DEFAULT_KEY_COLUMN
    value = request.key_value.strip()
    config_groups = _groups(db)

    conn = _conn()
    try:
        _ensure_tables(conn)
        summary = []
        for m in request.mapping:
            info = tiles.resolve_table(db, m.layer_table)
            g, role, mode = _group_for_layers(config_groups, m.layer_table)
            if not role:
                mode = request.modes.get(m.layer_table) or mode
            staged = os.path.join(tmp, m.file_base + "_staged.gpkg")
            shp_info = _read_shp(staged)

            with conn.cursor() as cur:
                action = _apply_layer_update(conn, cur, info, key, value, shp_info,
                                             g, role, mode, current_user)
                summary.append(action)
            _write_audit(conn, m.layer_table, action["action"], value,
                         action["old_count"], action["new_count"], current_user)
        if request.persist_classification:
            for lt, fmode in request.persist_classification.items():
                if fmode in ("update_in_place", "delete_and_insert"):
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO layer_update_mode (layer_table, update_mode, persist, created_by) "
                            "VALUES (%s, %s, TRUE, %s) "
                            "ON CONFLICT (layer_table) DO UPDATE SET update_mode = EXCLUDED.update_mode, "
                            "persist = TRUE, created_by = EXCLUDED.created_by",
                            (lt, fmode, getattr(current_user, "username", "system")))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "summary": summary,
        "updated": [s["layer_table"] for s in summary if s["status"] == "updated"],
        "skipped": [],
        "message": "Commit complete.",
    }


def _insert_new_features(conn, info: dict, key: str, value: str, gdf, attr_cols: list,
                         inherited: dict, user) -> int:
    """INSERT one DB row per uploaded feature (attributes + computed stats).

    Computed attributes (Area_SQM/Area_Feddan/X/Y) are derived from the
    inserted geometry server-side, mirroring migrate.py. Returns inserted count.
    """
    table = info["table"]
    geom_col = info["geom_col"]
    srid = info["srid"]
    family = _geom_family(info["gtype"])
    is_poly = family == "POLYGON"
    uname = getattr(user, "username", "system")

    records = []
    for idx in range(len(gdf)):
        geom = gdf.geometry.values[idx]
        if geom is None or getattr(geom, "is_empty", False):
            continue
        vals = []
        for c in attr_cols:
            if c == key:
                vals.append(value)
            elif c == "created_by":
                vals.append(uname)
            elif c in ("Area_SQM", "Area_Feddan", "X", "Y"):
                vals.append(None)  # computed server-side from geometry
            else:
                v = None
                if c in gdf.columns:
                    v = gdf.iloc[idx][c]
                if (v is None or (isinstance(v, float) and v != v)) and c in inherited:
                    v = inherited.get(c)
                vals.append(v.item() if hasattr(v, "item") else v)
        records.append(vals + [geom.wkt])

    if not records:
        raise HTTPException(status_code=400, detail=f"{table}: uploaded file has no usable features")

    vnames = ", ".join([_q(c) for c in attr_cols] + ["wkt"])
    col_sql = ", ".join([_q(c) for c in attr_cols + [geom_col]])
    geom_expr = (f"ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Force2D("
                 f"ST_GeomFromText(v.wkt, {srid}))), 3))" if is_poly else
                 f"ST_CollectionExtract(ST_Force2D(ST_GeomFromText(v.wkt, {srid})), 1)")
    items = []
    for c in attr_cols:
        if c == "Area_SQM" and is_poly:
            items.append("ROUND(ST_Area(d.geom)::numeric, 2)")
        elif c == "Area_Feddan" and is_poly:
            items.append(f"ROUND((ST_Area(d.geom) / {FEDDAN_CONSTANT})::numeric, 4)")
        elif c == "X":
            items.append("ST_X(ST_PointOnSurface(d.geom))")
        elif c == "Y":
            items.append("ST_Y(ST_PointOnSurface(d.geom))")
        else:
            items.append(f"v.{_q(c)}")
    items.append("d.geom")
    sql = (f"INSERT INTO {_q(table)} ({col_sql}) "
           f"SELECT {', '.join(items)} "
           f"FROM (VALUES %s) AS v({vnames}) "
           f"CROSS JOIN LATERAL (SELECT {geom_expr} AS geom) d "
           f"RETURNING id")
    template = "(" + ", ".join(["%s"] * (len(attr_cols) + 1)) + ")"
    with conn.cursor() as c:
        inserted = psycopg2.extras.execute_values(c, sql, records,
                                                  template=template, page_size=200, fetch=True)
    return len(inserted) if inserted else 0


def _apply_layer_update(conn, cur, info: dict, key: str, value: str, shp_info: dict,
                        g, role, mode, user) -> dict:
    """Run one layer's update inside the caller's transaction; archive first."""
    gdf = shp_info["gdf"]
    table = info["table"]
    geom_col = info["geom_col"]
    srid = info["srid"]
    is_poly = _geom_family(info["gtype"]) == "POLYGON"

    # -- 1) backup old features (everything for this request) ---------------
    old_rows = []
    with conn.cursor() as bc:
        bc.execute(
            f"SELECT to_jsonb(t) - '{geom_col}' AS props, "
            f"ST_AsGeoJSON(ST_Transform({_q(geom_col)}, 4326)) AS g "
            f"FROM {_q(table)} t WHERE {_q(key)} = %s", (value,))
        for props, gjson in bc.fetchall():
            old_rows.append({"properties": props,
                             "geometry": json.loads(gjson) if gjson else None})
    old_count = len(old_rows)

    attr_cols = [c for c in ("Req_Number", "Owner_Name", "Layer_Type",
                             "Area_SQM", "Area_Feddan", "X", "Y", "created_by")
                 if c in [x["name"] for x in info["columns"]] and c != geom_col
                 and (c not in ("Area_SQM", "Area_Feddan") or is_poly)]

    wkt_all = [g.wkt for g in gdf.geometry
               if g is not None and not getattr(g, "is_empty", False)]
    if not wkt_all:
        raise HTTPException(status_code=400, detail=f"{table}: no usable geometry in uploaded file")
    if role == "master" and len(wkt_all) != 1:
        raise HTTPException(status_code=400,
                            detail=f"Layer `{table}` allows only one feature per request number.")

    # inherited attributes from the master layer (per relationship config)
    inherit_src = None
    if role == "related" and g:
        for rel in (g["config"].get("related_layers") or []):
            if rel.get("name") == table:
                inherit_src = rel.get("inherit_attributes_from")
                break
    inherited = {}
    if inherit_src:
        with conn.cursor() as ic:
            ic.execute(f"SELECT to_jsonb(t) FROM {_q(inherit_src)} t "
                       f"WHERE {_q(key)} = %s LIMIT 1", (value,))
            row = ic.fetchone()
            if row:
                inherited = (row[0] if row[0] else {}) or {}

    # -- 2) update in place (master layer / explicit classification) ----------
    if role == "master" or mode == "update_in_place":
        if old_count == 0:
            # nothing exists to update: insert the replacement instead
            action = "BULK_REPLACE"
            new_count = _insert_new_features(conn, info, key, value, gdf,
                                             attr_cols, inherited, user)
            _archive(cur, action, table, key, value, old_rows, new_count, user)
            return {"layer_table": table, "action": action, "old_count": 0,
                    "new_count": new_count, "status": "inserted"}
        geom_expr = (f"ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Force2D("
                     f"ST_GeomFromText(%s, {srid}))), 3))" if is_poly else
                     f"ST_CollectionExtract(ST_Force2D(ST_GeomFromText(%s, {srid})), 1)")
        cur.execute(
            f"UPDATE {_q(table)} SET {_q(geom_col)} = {geom_expr} WHERE {_q(key)} = %s",
            (wkt_all[0], value))
        action = "UPDATE_IN_PLACE"
        _archive(cur, action, table, key, value, old_rows, len(wkt_all), user)
        return {"layer_table": table, "action": action, "old_count": old_count,
                "new_count": len(wkt_all), "status": "updated" if old_count else "no-op"}

    # -- 3) delete-and-insert (related layer / explicit classification) -------
    action = "BULK_REPLACE"
    with conn.cursor() as dc:
        dc.execute(f"DELETE FROM {_q(table)} WHERE {_q(key)} = %s", (value,))
    new_count = _insert_new_features(conn, info, key, value, gdf, attr_cols,
                                     inherited, user)
    _archive(cur, action, table, key, value, old_rows, new_count, user)
    return {"layer_table": table, "action": action, "old_count": old_count,
            "new_count": new_count, "status": "updated" if old_count else "inserted"}


def _archive(cur, action: str, table: str, key: str, value: str, old_rows: list, new_count: int,
             user=None):
    cur.execute(
        "INSERT INTO update_archive (action, layer_table, key_column, key_value, old_count, "
        "new_count, old_geojson, new_geojson, user_id, username) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s) RETURNING id",
        (action, table, key, value, len(old_rows), new_count,
         json.dumps(old_rows, ensure_ascii=False, default=str),
         getattr(user, "id", None), getattr(user, "username", "system")))
    return cur.fetchone()[0]


def _write_audit(conn, table: str, action: str, key_value: str, old_count: int, new_count: int, user):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_trail (table_name, record_id, action, old_values, new_values, "
            "user_id, username, created_at, timestamp) "
            "VALUES (%s, NULL, %s, %s::jsonb, %s::jsonb, %s, %s, NOW(), NOW())",
            (table, action,
             json.dumps({"key_column": DEFAULT_KEY_COLUMN, "key_value": key_value,
                         "old_count": old_count}, ensure_ascii=False),
             json.dumps({"key_column": DEFAULT_KEY_COLUMN, "key_value": key_value,
                         "new_count": new_count}, ensure_ascii=False),
             getattr(user, "id", None), getattr(user, "username", "system")),
        )


@router.get("/history")
def history(limit: int = 30, db: Session = Depends(deps.get_db),
            current_user=Depends(deps.get_current_user)):
    rows = db.execute(text(
        "SELECT id, action, layer_table, key_column, key_value, old_count, new_count, "
        "username, created_at, undone_at, undone_by FROM update_archive "
        "ORDER BY created_at DESC LIMIT :lim"
    ), {"lim": min(max(limit, 1), 200)}).mappings().all()
    return {"items": [dict(r) for r in rows]}


@router.post("/undo")
def undo(archive_id: int, db: Session = Depends(deps.get_db),
         current_user=Depends(deps.get_current_active_editor)):
    conn = _conn()
    try:
        _ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action, layer_table, key_column, key_value, old_geojson, old_count, "
                "created_at, undone_at FROM update_archive WHERE id = %s", (archive_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Archive entry not found")
            (aid, action, table, key, value, old_geojson, old_count, created_at, undone_at) = row
            if undone_at:
                raise HTTPException(status_code=400, detail="This update was already undone")
            if datetime.now() - created_at.replace(tzinfo=None) > UNDO_TTL:
                raise HTTPException(status_code=400,
                                    detail="Undo window (24h) has passed for this update.")

            old_rows = old_geojson if isinstance(old_geojson, (list, dict)) else json.loads(old_geojson or "[]")
            gcol = _geom_col(db, table)
            srid = _srid(db, table)
            is_poly = _is_polygon_family(table, conn)

            if action == "UPDATE_IN_PLACE":
                # restore archived geometry row-by-row (attributes untouched)
                for feat in old_rows:
                    g = feat.get("geometry")
                    props = feat.get("properties") or {}
                    rid = props.get("id")
                    if not g or rid is None:
                        continue
                    src = "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
                    if is_poly:
                        geom_sql = (f"ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Force2D("
                                    f"ST_Transform({src}, {srid}))), 3))")
                    else:
                        geom_sql = (f"ST_CollectionExtract(ST_Force2D("
                                    f"ST_Transform({src}, {srid})), 1)")
                    cur.execute(
                        f"UPDATE {_q(table)} SET {_q(gcol)} = {geom_sql} WHERE id = %s",
                        (json.dumps(g), rid))
            else:
                # delete current rows for request and re-insert archived originals
                cur.execute(f"DELETE FROM {_q(table)} WHERE {_q(key)} = %s", (value,))
                for feat in old_rows:
                    g = feat.get("geometry")
                    props = feat.get("properties") or {}
                    if not g:
                        continue
                    cols = [k for k in props.keys()
                            if str(k).lower() not in ("geometry", "id", "created_at")]
                    src = "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
                    if is_poly:
                        geom_sql = (f"ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Force2D("
                                    f"ST_Transform({src}, {srid}))), 3))")
                    else:
                        geom_sql = (f"ST_CollectionExtract(ST_Force2D("
                                    f"ST_Transform({src}, {srid})), 1)")
                    col_sql = ", ".join(_q(c) for c in cols)
                    cur.execute(
                        f"INSERT INTO {_q(table)} ({_q(gcol)}, {col_sql}) "
                        f"SELECT {geom_sql}, {', '.join(['%s'] * len(cols))}",
                        [json.dumps(g)] + [props[k] for k in cols])

            cur.execute("UPDATE update_archive SET undone_at = NOW(), undone_by = %s WHERE id = %s",
                        (getattr(current_user, "username", "system"), aid))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Undo failed: {str(e)}")
    finally:
        conn.close()
    return {"status": "undone", "archive_id": archive_id}


def _is_polygon_family(table: str, conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT type FROM geometry_columns WHERE f_table_name = %s", (table,))
        r = cur.fetchone()
    return bool(r and "POLYGON" in (r[0] or "").upper())


def _geom_col(db: Session, table: str) -> str:
    return tiles.resolve_table(db, table)["geom_col"]


def _srid(db: Session, table: str) -> int:
    return tiles.resolve_table(db, table)["srid"]


@router.post("/classify")
def classify(request: ClassifyRequest, db: Session = Depends(deps.get_db),
             current_user=Depends(deps.get_current_active_editor)):
    if request.update_mode not in ("update_in_place", "delete_and_insert"):
        raise HTTPException(status_code=400, detail="Invalid update mode")
    conn = _conn()
    try:
        _ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO layer_update_mode (layer_table, update_mode, persist, created_by) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (layer_table) DO UPDATE SET update_mode = EXCLUDED.update_mode, "
                "persist = EXCLUDED.persist, created_by = EXCLUDED.created_by",
                (request.layer_table, request.update_mode, request.persist,
                 getattr(current_user, "username", "system")))
        conn.commit()
    finally:
        conn.close()
    return {"status": "classified", "layer_table": request.layer_table,
            "update_mode": request.update_mode, "persist": request.persist}


@router.get("/groups")
def list_groups(db: Session = Depends(deps.get_db), current_user=Depends(deps.get_current_user)):
    return {"items": _groups(db)}


@router.post("/groups")
def create_group(request: GroupIn, db: Session = Depends(deps.get_db),
                 current_user=Depends(deps.get_current_active_admin)):
    conn = _conn()
    try:
        _ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO update_relationship_groups (group_key, name, config) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (group_key) DO UPDATE SET name = EXCLUDED.name, config = EXCLUDED.config "
                "RETURNING id",
                (request.group_key, request.name, json.dumps(request.config, ensure_ascii=False)))
            gid = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return {"status": "saved", "id": gid, "group_key": request.group_key}