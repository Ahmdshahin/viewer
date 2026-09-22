"""Admin-only Postgres connection management.

Lets an admin view, test, and switch the Postgres connection string at
runtime (stored in backend/db_connection.json, applied immediately without
a restart). Passwords are never returned by the API.
"""

from typing import List, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api import deps
from app.api.deps import get_current_active_admin, get_current_user
from app.core import config as config_mod
from app.core.config import settings
from app.db import session as session_mod
from app.db.models import User

router = APIRouter()

REQUIRED_TABLES = {"users", "lands", "eshghalat", "points", "audit_trail"}


class ConnectionIn(BaseModel):
    host: str
    port: int
    user: str
    password: Optional[str] = None
    db: str


def _public_view() -> dict:
    return {
        "host": settings.POSTGRES_SERVER,
        "port": settings.POSTGRES_PORT,
        "user": settings.POSTGRES_USER,
        "db": settings.POSTGRES_DB,
        "has_password": bool(settings.POSTGRES_PASSWORD),
        "database_url": (
            f"postgresql://{settings.POSTGRES_USER}:***"
            f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        ),
    }


def _connect(host, port, user, password, db, timeout=5):
    try:
        return psycopg2.connect(host=host, port=port, user=user,
                                password=password or "", dbname=db,
                                connect_timeout=timeout)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e!r}")


def _check_schema(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public';")
        tables = {r[0] for r in cur.fetchall()}
    missing = sorted(REQUIRED_TABLES - tables)
    return {"tables_found": sorted(tables & REQUIRED_TABLES), "missing_tables": missing}


@router.get("/connection")
def get_connection(current_user: User = Depends(get_current_active_admin)):
    """Show the active connection (password never exposed)."""
    return _public_view()


@router.post("/test")
def test_connection(body: ConnectionIn, current_user: User = Depends(get_current_active_admin)):
    """Test a connection string without saving or switching anything."""
    conn = _connect(body.host, body.port, body.user, body.password, body.db)
    try:
        info = _check_schema(conn)
    finally:
        conn.close()
    return {"ok": True, **info}


@router.post("/connection")
def save_connection(body: ConnectionIn, current_user: User = Depends(get_current_active_admin)):
    """Validate, save, and immediately switch to a new connection string."""
    password = body.password if body.password else settings.POSTGRES_PASSWORD
    conn = _connect(body.host, body.port, body.user, password, body.db)
    try:
        info = _check_schema(conn)
    finally:
        conn.close()
    if info["missing_tables"]:
        raise HTTPException(
            status_code=400,
            detail=f"Target database is missing geoportal tables: {', '.join(info['missing_tables'])}",
        )

    values = {
        "POSTGRES_SERVER": body.host,
        "POSTGRES_PORT": body.port,
        "POSTGRES_USER": body.user,
        "POSTGRES_DB": body.db,
    }
    if body.password:
        values["POSTGRES_PASSWORD"] = body.password
    config_mod.save_connection_file(values)
    config_mod.apply_connection_file()
    session_mod.reset_engine()

    # Prove the fresh engine actually connects under the new settings
    try:
        with session_mod.get_engine().connect() as c:
            c.exec_driver_sql("SELECT 1")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Saved, but new engine failed to connect: {e!r}")

    return {"applied": True, **_public_view()}


# ---------- Map layers curation ----------

DEFAULT_MAP_LAYERS = [
    {"table": "lands", "label": "Land Parcels", "visible": True, "color": "#e74c3c", "sort_order": 1},
    {"table": "eshghalat", "label": "Eshghalat", "visible": True, "color": "#3498db", "sort_order": 2},
    {"table": "points", "label": "Points", "visible": True, "color": "#27ae60", "sort_order": 3},
]

PALETTE = ["#e74c3c", "#3498db", "#27ae60", "#f39c12", "#9b59b6",
           "#1abc9c", "#e67e22", "#8e44ad"]


class MapLayerIn(BaseModel):
    table: str
    label: str
    visible: bool = True
    color: str = "#3388ff"


def _map_conn():
    import psycopg2
    return psycopg2.connect(
        host=settings.POSTGRES_SERVER, port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER, password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB)


def _ensure_map_layers(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS map_layers (
                table_name VARCHAR(100) PRIMARY KEY,
                label VARCHAR(200) NOT NULL,
                visible BOOLEAN NOT NULL DEFAULT TRUE,
                color VARCHAR(20) NOT NULL DEFAULT '#3388ff',
                sort_order INTEGER NOT NULL DEFAULT 100
            );
        """)
        for d in DEFAULT_MAP_LAYERS:
            cur.execute(
                """INSERT INTO map_layers (table_name, label, visible, color, sort_order)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (table_name) DO NOTHING;""",
                (d["table"], d["label"], d["visible"], d["color"], d["sort_order"]),
            )
    conn.commit()


def _table_columns(conn, table: str) -> list:
    with conn.cursor() as cur:
        cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = %s
                       ORDER BY ordinal_position;""", (table,))
        return [{"name": r[0], "type": r[1]} for r in cur.fetchall()]


def _spatial_tables(conn) -> list:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT g.f_table_name AS table, g.f_geometry_column AS geom_col,
                   g.type AS gtype, g.srid AS srid
            FROM geometry_columns g
            JOIN pg_class c ON c.relname = g.f_table_name
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            WHERE g.f_table_name NOT IN ('spatial_ref_sys')
            ORDER BY g.f_table_name;
        """)
        tables = [{"table": r[0], "geom_col": r[1], "gtype": r[2], "srid": r[3]}
                  for r in cur.fetchall()]
    out = []
    for t in tables:
        cols = _table_columns(conn, t["table"])
        names = [c["name"] for c in cols]
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{t["table"]}";')
                t["count"] = int(cur.fetchone()[0])
        except Exception:
            conn.rollback()
            t["count"] = -1
        # label field: preferred display column for map labels
        t["label_field"] = None
        for cand in ("Req_Number", "Owner_Name", "name", "label", "title"):
            if cand in names:
                t["label_field"] = cand
                break
        if t["label_field"] is None:
            for c in cols:
                if c["type"] in ("character varying", "text", "character") and c["name"] != t["geom_col"]:
                    t["label_field"] = c["name"]
                    break
        t["columns"] = names
        out.append(t)
    return out


@router.get("/map-layers")
def list_map_layers(current_user: User = Depends(get_current_active_admin)):
    """All spatial tables + current curation (admin)."""
    conn = _map_conn()
    try:
        _ensure_map_layers(conn)
        available = _spatial_tables(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT table_name, label, visible, color, sort_order FROM map_layers;")
            cfg = {r[0]: {"label": r[1], "visible": r[2], "color": r[3], "sort_order": r[4]}
                   for r in cur.fetchall()}
    finally:
        conn.close()
    items, order = [], 0
    for t in available:
        c = cfg.get(t["table"], {})
        items.append({**t,
                      "label": c.get("label") or t["table"],
                      "visible": c.get("visible", False),
                      "color": c.get("color") or PALETTE[order % len(PALETTE)],
                      "sort_order": c.get("sort_order", 900)})
        order += 1
    for name, c in cfg.items():
        if not any(t["table"] == name for t in available):
            items.append({"table": name, "missing": True, **c})
    return {"layers": sorted(items, key=lambda r: (r["sort_order"], r["table"]))}


@router.post("/map-layers")
def save_map_layers(items: List[MapLayerIn],
                    current_user: User = Depends(get_current_active_admin)):
    """Save the curated map layer list (admin)."""
    conn = _map_conn()
    try:
        _ensure_map_layers(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT f_table_name FROM geometry_columns;")
            known = {r[0] for r in cur.fetchall()}
        order = 10
        saved = 0
        with conn.cursor() as cur:
            for it in items:
                if it.table not in known:
                    raise HTTPException(status_code=400, detail=f"Unknown spatial table: {it.table}")
                color = it.color if str(it.color).startswith("#") else "#3388ff"
                cur.execute(
                    """INSERT INTO map_layers (table_name, label, visible, color, sort_order)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (table_name) DO UPDATE SET
                         label = EXCLUDED.label, visible = EXCLUDED.visible,
                         color = EXCLUDED.color, sort_order = EXCLUDED.sort_order;""",
                    (it.table, it.label[:200], bool(it.visible), color[:20], order),
                )
                order += 10
                saved += 1
        conn.commit()
    finally:
        conn.close()
    return {"saved": saved}


@router.get("/map-layers/visible")
def visible_map_layers(current_user: User = Depends(deps.get_current_user)):
    """Curated visible layers for the map viewer (any logged-in user)."""
    conn = _map_conn()
    out = []
    try:
        _ensure_map_layers(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.table_name, m.label, m.visible, m.color, m.sort_order,
                       g.f_geometry_column AS geom_col, g.type AS gtype, g.srid AS srid
                FROM map_layers m
                LEFT JOIN geometry_columns g ON g.f_table_name = m.table_name
                WHERE m.visible = TRUE
                ORDER BY m.sort_order, m.table_name;
            """)
            raw = cur.fetchall()
        for r in raw:
            it = {"table": r[0], "label": r[1], "visible": r[2], "color": r[3],
                  "sort_order": r[4], "geom_col": r[5], "gtype": r[6], "srid": r[7]}
            if not it["geom_col"]:
                continue
            cols = _table_columns(conn, it["table"])
            names = [c["name"] for c in cols]
            lf = None
            for cand in ("Req_Number", "Owner_Name", "name", "label", "title"):
                if cand in names:
                    lf = cand
                    break
            if lf is None:
                for c in cols:
                    if c["type"] in ("character varying", "text", "character") and c["name"] != it["geom_col"]:
                        lf = c["name"]
                        break
            it["label_field"] = lf
            out.append(it)
    finally:
        conn.close()
    return {"layers": out}
