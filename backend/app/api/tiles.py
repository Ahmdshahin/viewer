"""Scalable map serving for any spatial table (1M+ features).

- Vector tiles (MVT) for rendering: full fidelity at street zoom (z>=15),
  generalized overviews below (rendering-only; stored data untouched).
- Stats, paginated rows (dynamic columns), and server-evaluated attribute
  selections so tables and filters work without downloading whole layers.
- Named selections shared with tiles/stats/rows/export via selections.py.
- Any public PostGIS table with a geometry column works, not just the
  cadastral trio. Request-number features (select, selections) require a
  Req_Number column and report a clear 400 otherwise.
"""

from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.api import selections
from app.core.security import decode_access_token
from app.db.models import User

router = APIRouter()

TEXT_OPS = ("contains", "=", "!=")
NUM_OPS = ("=", "!=", ">", "<", ">=", "<=")
DATE_OPS = ("=", ">=", "<=")

_NUM_TYPES = {"smallint", "integer", "bigint", "real", "double precision",
              "numeric", "decimal", "smallserial", "serial", "bigserial"}
_TEXT_TYPES = {"character varying", "varchar", "character", "char", "text", "uuid"}
_DATE_TYPES = {"date", "timestamp without time zone", "timestamp with time zone",
               "timestamp", "timestamptz"}

_info_cache: Dict[str, dict] = {}


class Cond(BaseModel):
    field: str
    op: str
    value: str


class SelectIn(BaseModel):
    conds: List[Cond]


class SelectionIn(BaseModel):
    reqs: List[str]


def _q(name: str) -> str:
    return '"' + name.replace('"', '') + '"'


def resolve_table(db: Session, table: str) -> dict:
    """Catalog info for any public spatial table (cached). 400 if not spatial."""
    if table in _info_cache:
        return _info_cache[table]
    row = db.execute(text("""
        SELECT g.f_geometry_column AS geom_col, g.type AS gtype, g.srid AS srid
        FROM geometry_columns g
        JOIN pg_class c ON c.relname = g.f_table_name
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        WHERE g.f_table_name = :t;
    """), {"t": table}).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail=f"Not a spatial table: {table}")
    cols = db.execute(text("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t
        ORDER BY ordinal_position;
    """), {"t": table}).mappings().all()
    info = {"table": table, "geom_col": row["geom_col"],
            "gtype": (row["gtype"] or "").upper(),
            "srid": int(row["srid"] or 0) or 32636,
            "columns": [{"name": c["column_name"], "type": c["data_type"]} for c in cols]}
    _info_cache[table] = info
    return info


def _has_col(info: dict, col: str) -> bool:
    return any(c["name"] == col for c in info["columns"])


def _require_req(info: dict) -> None:
    if not _has_col(info, "Req_Number"):
        raise HTTPException(status_code=400,
                            detail=f"Table {info['table']} has no Req_Number column")


def _data_cols(info: dict) -> list:
    return [c["name"] for c in info["columns"] if c["name"] != info["geom_col"]]


def _parse_box(box) -> Optional[list]:
    """'BOX(x1 y1,x2 y2)' -> [x1, y1, x2, y2]."""
    if not box:
        return None
    try:
        inner = str(box).strip()[4:-1]
        first, second = inner.split(",")
        x1, y1 = first.strip().split()
        x2, y2 = second.strip().split()
        return [float(x1), float(y1), float(x2), float(y2)]
    except Exception:
        return None


def _row_to_item(row) -> dict:
    d = dict(row)
    bb = _parse_box(d.pop("bb", None))
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    d["bbox"] = bb
    return d


@router.get("/{layer_name}/tiles/{z}/{x}/{y}.pbf")
def get_tile(layer_name: str, z: int, x: int, y: int,
             request: Request,
             sel: Optional[str] = Query(None),
             token: Optional[str] = Query(None),
             db: Session = Depends(deps.get_db)):
    # Map tiles cannot send Authorization headers, so ?token= is accepted.
    # The token is read here (not in a sub-dependency) by design.
    raw = request.headers.get("Authorization")
    hdr = raw[7:] if raw and raw.lower().startswith("bearer ") else None
    tok = hdr or token
    token_data = decode_access_token(tok) if tok else None
    if not token_data:
        raise HTTPException(status_code=401, detail="Could not validate credentials",
                            headers={"WWW-Authenticate": "Bearer"})
    current_user = db.query(User).filter(User.username == token_data.get("username")).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    info = resolve_table(db, layer_name)
    if not (0 <= z <= 22 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(status_code=404, detail="Invalid tile coordinates")

    G = _q(info["geom_col"])
    reqs = None
    if sel is not None:
        _require_req(info)
        reqs = selections.get_selection(sel)
        if reqs is None:
            raise HTTPException(status_code=404, detail="Selection expired, please re-select")
        if not reqs:
            return Response(status_code=204)

    # No geometric simplification at any zoom: parcels are often smaller than
    # a generalization tolerance, which collapses them to nothing and empties
    # overview tiles. Tiles stay fast via clipping + binary encoding instead.
    geom_expr = f"ST_Transform(ST_MakeValid({G}), 3857)"

    where = f"ST_Intersects({G}, ST_Transform(ST_TileEnvelope(:z, :x, :y), {info['srid']}))"
    params: Dict = {"z": z, "x": x, "y": y}
    if reqs is not None:
        where += ' AND "Req_Number" = ANY(:reqs)'
        params["reqs"] = reqs

    # NOTE: keep property list smallish; full attributes come from rows/identify.
    # Properties are emitted dynamically so any spatial table tiles cleanly,
    # even ones without an id / Req_Number / Owner_Name column.
    mvt_props = ", ".join([_q(c) for c in ("id", "Req_Number", "Owner_Name") if _has_col(info, c)])
    sql = text(f"""
        SELECT ST_AsMVT(q, :lname, 4096, 'geom') FROM (
          SELECT {mvt_props + (", " if mvt_props else "")}ST_AsMVTGeom({geom_expr}, ST_TileEnvelope(:z, :x, :y), 4096, 64, true) AS geom
          FROM {_q(layer_name)}
          WHERE {where}
        ) q;
    """)
    params["lname"] = {"lands": "land", "eshghalat": "eshghalat",
                       "points": "point"}.get(layer_name, layer_name)
    data = db.execute(sql, params).scalar()
    if not data:
        return Response(status_code=204)
    return Response(content=bytes(data), media_type="application/x-protobuf")


@router.get("/{layer_name}/stats")
def layer_stats(layer_name: str, sel: Optional[str] = Query(None),
                db: Session = Depends(deps.get_db),
                current_user: User = Depends(deps.get_current_user)):
    info = resolve_table(db, layer_name)
    G = _q(info["geom_col"])
    where, params = "", {}
    if sel is not None:
        _require_req(info)
        reqs = selections.get_selection(sel)
        if reqs is None:
            raise HTTPException(status_code=404, detail="Selection expired, please re-select")
        where = 'WHERE "Req_Number" = ANY(:reqs)'
        params = {"reqs": reqs}

    if _has_col(info, "Area_SQM"):
        area_expr = 'COALESCE(SUM("Area_SQM"), 0)'
    else:
        area_expr = "0"
    row = db.execute(text(f"""
        SELECT COUNT(*) AS n, {area_expr} AS a
        FROM {_q(layer_name)} {where};
    """), params).mappings().first()
    bbox = db.execute(text(f"""
        SELECT ST_XMin(g) AS x1, ST_YMin(g) AS y1, ST_XMax(g) AS x2, ST_YMax(g) AS y2 FROM (
          SELECT ST_Transform(ST_SetSRID(ST_Extent({G})::geometry, {info['srid']}), 4326) AS g
          FROM {_q(layer_name)} {where}
        ) s;
    """), params).mappings().first()

    total_area = float(row["a"] or 0)
    bb = None
    if bbox and bbox["x1"] is not None:
        bb = [bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]]
    return {
        "count": int(row["n"]),
        "total_area_sqm": round(total_area, 2),
        "total_area_feddan": round(total_area / 4200.8333, 4),
        "bbox": bb,
    }


@router.get("/{layer_name}/rows")
def layer_rows(layer_name: str,
               limit: int = Query(50, ge=1, le=500),
               offset: int = Query(0, ge=0),
               q: str = Query(""),
               sel: Optional[str] = Query(None),
               db: Session = Depends(deps.get_db),
               current_user: User = Depends(deps.get_current_user)):
    info = resolve_table(db, layer_name)
    G = _q(info["geom_col"])
    cols = _data_cols(info)
    if not cols:
        raise HTTPException(status_code=400, detail=f"Table {layer_name} has no attribute columns")
    select_list = ", ".join([_q(c) for c in cols])
    order_col = "id" if "id" in cols else cols[0]

    conds, params = [], {}
    if sel is not None:
        _require_req(info)
        reqs = selections.get_selection(sel)
        if reqs is None:
            raise HTTPException(status_code=404, detail="Selection expired, please re-select")
        conds.append('"Req_Number" = ANY(:reqs)')
        params["reqs"] = reqs
    if q:
        if _has_col(info, "Req_Number") and _has_col(info, "Owner_Name"):
            conds.append('("Req_Number" ILIKE :q OR "Owner_Name" ILIKE :q)')
            params["q"] = f"%{q}%"
        elif _has_col(info, "Req_Number"):
            conds.append('"Req_Number" ILIKE :q')
            params["q"] = f"%{q}%"
        else:
            raise HTTPException(status_code=400, detail="Text search needs a Req_Number column")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    count_params = {k: v for k, v in params.items() if k in ("reqs", "q")}
    total = db.execute(
        text(f"SELECT COUNT(*) FROM {_q(layer_name)} {where};"), count_params).scalar() or 0
    params.update({"limit": limit, "offset": offset})

    rows = db.execute(text(f"""
        SELECT {select_list},
               Box2D(ST_Transform({G}, 4326)) AS bb
        FROM {_q(layer_name)} {where}
        ORDER BY {_q(order_col)} LIMIT :limit OFFSET :offset;
    """), params).mappings().all()
    cols_meta = [{"name": c["name"], "type": c["type"]}
                 for c in info["columns"] if c["name"] != info["geom_col"]]
    return {"items": [_row_to_item(r) for r in rows], "total": int(total),
            "columns": cols_meta}


def _build_where(info: dict, conds: List[Cond]):
    """Safe WHERE builder over per-table whitelisted fields."""
    col_types = {c["name"]: c["type"] for c in info["columns"]}
    fragments, params = [], {}
    for i, c in enumerate(conds):
        if c.field == info["geom_col"] or c.field not in col_types:
            raise HTTPException(status_code=400, detail=f"Invalid field: {c.field}")
        t = col_types[c.field]
        if t in ("character varying", "varchar", "character", "char", "text", "uuid"):
            ftype = "text"
        elif t in ("smallint", "integer", "bigint", "real", "double precision",
                   "numeric", "decimal", "smallserial", "serial", "bigserial"):
            ftype = "num"
        elif t in ("date", "timestamp without time zone", "timestamp with time zone",
                   "timestamp", "timestamptz"):
            ftype = "date"
        else:
            ftype = "text"
        if not c.value or not str(c.value).strip():
            raise HTTPException(status_code=400, detail=f"Empty value for {c.field}")
        val = str(c.value).strip()
        key = f"p{i}"
        col = _q(c.field)
        if ftype == "text":
            if c.op not in TEXT_OPS:
                raise HTTPException(status_code=400, detail=f"Invalid operator for {c.field}")
            if c.op == "contains":
                fragments.append(f'{col} ILIKE :{key}')
                params[key] = f"%{val}%"
            elif c.op == "=":
                fragments.append(f'{col} = :{key}')
                params[key] = val
            else:
                fragments.append(f'({col} IS DISTINCT FROM :{key})')
                params[key] = val
        elif ftype == "num":
            if c.op not in NUM_OPS:
                raise HTTPException(status_code=400, detail=f"Invalid operator for {c.field}")
            try:
                num = float(val)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Not a number: {val}")
            fragments.append(f"(CASE WHEN {col}::text ~ '^[+-]?[0-9.]+$' THEN {col}::float ELSE NULL END) {c.op} :{key}")
            params[key] = num
        else:  # date
            if c.op not in DATE_OPS:
                raise HTTPException(status_code=400, detail=f"Invalid operator for {c.field}")
            try:
                day = date.fromisoformat(val[:10])
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Not a date: {val}")
            fragments.append(f"{col}::date {c.op} :{key}")
            params[key] = day.isoformat()
    return ("WHERE " + " AND ".join(fragments)) if fragments else "", params


@router.post("/{layer_name}/select")
def layer_select(layer_name: str, body: SelectIn,
                 db: Session = Depends(deps.get_db),
                 current_user: User = Depends(deps.get_current_user)):
    info = resolve_table(db, layer_name)
    if not body.conds:
        raise HTTPException(status_code=400, detail="At least one condition is required")
    where, params = _build_where(info, body.conds)
    G = _q(info["geom_col"])

    count = db.execute(
        text(f"SELECT COUNT(*) FROM {_q(layer_name)} {where};"), params).scalar() or 0
    if count == 0:
        return {"count": 0, "bbox": None, "sample": [], "selection_id": None}

    bbox = db.execute(text(f"""
        SELECT ST_XMin(g) AS x1, ST_YMin(g) AS y1, ST_XMax(g) AS x2, ST_YMax(g) AS y2 FROM (
          SELECT ST_Transform(ST_SetSRID(ST_Extent({G})::geometry, {info['srid']}), 4326) AS g
          FROM {_q(layer_name)} {where}
        ) s;
    """), params).mappings().first()
    bb = [bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]] if bbox and bbox["x1"] is not None else None

    cols = _data_cols(info)
    select_list = ", ".join([_q(c) for c in cols])
    order_col = "id" if "id" in cols else cols[0]
    sample = db.execute(text(f"""
        SELECT {select_list}, Box2D(ST_Transform({G}, 4326)) AS bb
        FROM {_q(layer_name)} {where}
        ORDER BY {_q(order_col)} LIMIT 200;
    """), params).mappings().all()

    sid = None
    if _has_col(info, "Req_Number"):
        req_rows = db.execute(
            text(f'SELECT DISTINCT "Req_Number" FROM {_q(layer_name)} {where};'), params).fetchall()
        sid = selections.create_selection([r[0] for r in req_rows if r[0]])
    return {"count": count, "bbox": bb,
            "sample": [_row_to_item(r) for r in sample], "selection_id": sid}


@router.post("/selections")
def create_sel(body: SelectionIn,
               db: Session = Depends(deps.get_db),
               current_user: User = Depends(deps.get_current_user)):
    if not body.reqs:
        raise HTTPException(status_code=400, detail="Empty request list")
    sid = selections.create_selection(body.reqs)
    return {"selection_id": sid, "count": len(body.reqs)}


@router.delete("/selections/{sid}")
def delete_sel(sid: str,
               db: Session = Depends(deps.get_db),
               current_user: User = Depends(deps.get_current_user)):
    selections.delete_selection(sid)
    return {"deleted": sid}
