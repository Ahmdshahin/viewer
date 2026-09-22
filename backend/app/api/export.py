"""Export PostGIS layers to downloadable files.

Formats: GeoJSON (.geojson), CSV (.csv), Shapefile (.zip), GeoPackage (.gpkg),
File Geodatabase (.gdb in a .zip). Optional per-layer request-number filters
let the export honor the map's current filtered view.
"""

import os
import shutil
import tempfile
import zipfile
from typing import Dict, List, Optional

import geopandas as gpd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTasks

from app.api import deps
from app.api import selections
from app.db.models import User
from app.db.session import get_engine

router = APIRouter()

TABLES = ("lands", "eshghalat", "points")
FORMATS = ("geojson", "csv", "shp", "gpkg", "filegdb")

# Shapefile/DBF-safe column names (10 chars max)
SHP_COLUMNS = {
    "Req_Number": "Req_Number",
    "Owner_Name": "Owner_Name",
    "Layer_Type": "Layer_Type",
    "Area_SQM": "Area_SQM",
    "Area_Feddan": "Area_Fed",
    "X": "X",
    "Y": "Y",
    "created_by": "created_by",
}


class ExportIn(BaseModel):
    layers: List[str] = ["land", "eshghalat", "point"]
    format: str = "geojson"
    filters: Optional[Dict[str, List[str]]] = None
    sel: Optional[str] = None  # named selection: same request set on every layer


def _read_layer(table: str, reqs) -> gpd.GeoDataFrame:
    sql = f"SELECT * FROM {table}"
    params = None
    if reqs:
        sql += ' WHERE "Req_Number" = ANY(%(reqs)s)'
        params = {"reqs": list(reqs)}
    gdf = gpd.read_postgis(sql, get_engine(), geom_col="geometry", params=params)
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=32636)
    return gdf


def _lonlat(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=32636)
    return gdf.to_crs(epsg=4326) if gdf.crs.to_epsg() != 4326 else gdf


def _cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)


@router.post("/run")
def export_run(body: ExportIn, background: BackgroundTasks,
               current_user: User = Depends(deps.get_current_user)):
    from sqlalchemy import text as _text
    from app.db.session import SessionLocal as _SessionLocal
    from app.db.session import get_engine as _get_engine
    from app.api.tiles import resolve_table as _resolve
    db = _SessionLocal(bind=_get_engine())
    try:
        layers = []
        for l in (body.layers or []):
            try:
                _resolve(db, l)
                layers.append(l)
            except HTTPException:
                continue
        if not layers:
            raise HTTPException(status_code=400, detail="No valid spatial layers selected.")
    finally:
        db.close()
    if body.format not in FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported format. Choose: {', '.join(FORMATS)}")

    tmpdir = tempfile.mkdtemp(prefix="geoexport_")
    try:
        sel_reqs = None
        if body.sel:
            sel_reqs = selections.get_selection(body.sel)
            if sel_reqs is None:
                raise HTTPException(status_code=404, detail="Selection expired, please re-select")

        def _layer_reqs(table: str):
            if body.sel:
                return sel_reqs
            return (body.filters or {}).get(table)

        produced = []  # (arcname, realpath) for zip, or single file path
        single_path = None

        if body.format == "gpkg":
            out = os.path.join(tmpdir, "export.gpkg")
            wrote = False
            for table in layers:
                gdf = _read_layer(table, _layer_reqs(table))
                if gdf.empty:
                    continue
                gdf.to_file(out, layer=table, driver="GPKG")
                wrote = True
            if not wrote:
                raise HTTPException(status_code=400, detail="Nothing to export (empty selection).")
            single_path = (out, "export.gpkg", "application/geopackage+sqlite3")

        elif body.format == "filegdb":
            gdbdir = os.path.join(tmpdir, "export.gdb")
            wrote = False
            for table in layers:
                gdf = _read_layer(table, _layer_reqs(table))
                if gdf.empty:
                    continue
                try:
                    gdf.to_file(gdbdir, layer=table, driver="OpenFileGDB")
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"FileGDB write failed: {e!r}")
                wrote = True
            if not wrote:
                raise HTTPException(status_code=400, detail="Nothing to export (empty selection).")
            zip_path = os.path.join(tmpdir, "export_gdb.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for root, _, files in os.walk(gdbdir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, tmpdir))
            single_path = (zip_path, "export_gdb.zip", "application/zip")

        else:
            for table in layers:
                gdf = _read_layer(table, _layer_reqs(table))
                if gdf.empty:
                    continue
                if body.format == "geojson":
                    out = os.path.join(tmpdir, f"{table}.geojson")
                    _lonlat(gdf).to_file(out, driver="GeoJSON")
                    produced.append((f"{table}.geojson", out))
                elif body.format == "csv":
                    g4326 = _lonlat(gdf)
                    df = g4326.drop(columns="geometry").copy()
                    try:
                        cent = g4326.geometry.centroid
                        df["Longitude"] = cent.x
                        df["Latitude"] = cent.y
                    except Exception:
                        pass
                    out = os.path.join(tmpdir, f"{table}.csv")
                    df.to_csv(out, index=False, encoding="utf-8-sig")
                    produced.append((f"{table}.csv", out))
                elif body.format == "shp":
                    if set(SHP_COLUMNS) & set(gdf.columns):
                        cols = [c for c in SHP_COLUMNS if c in gdf.columns]
                        sub = gdf[cols + ["geometry"]].rename(columns=SHP_COLUMNS)
                    else:
                        # Custom table: all non-geometry columns, DBF-safe names
                        keep = [c for c in gdf.columns
                                if c != "geometry" and "date" not in c.lower()
                                and "time" not in c.lower()]
                        seen, ren = set(), {}
                        for c in keep:
                            base, i = c[:10], 1
                            while base in seen:
                                i += 1
                                base = (c[:8] + str(i))[:10]
                            seen.add(base)
                            ren[c] = base
                        sub = gdf[keep + ["geometry"]].rename(columns=ren)
                    shpdir = os.path.join(tmpdir, f"{table}_shp")
                    os.makedirs(shpdir, exist_ok=True)
                    sub.to_file(os.path.join(shpdir, f"{table}.shp"), driver="ESRI Shapefile")
                    for fn in os.listdir(shpdir):
                        produced.append((f"{table}_shp/{fn}", os.path.join(shpdir, fn)))

            if not produced:
                raise HTTPException(status_code=400, detail="Nothing to export (empty selection).")
            if len(produced) == 1 and body.format in ("geojson", "csv"):
                arc, real = produced[0]
                mime = "application/geo+json" if arc.endswith(".geojson") else "text/csv"
                single_path = (real, arc, mime)

        if single_path:
            real, arc, mime = single_path
            background.add_task(_cleanup, tmpdir)
            return FileResponse(real, media_type=mime, filename=arc, background=background)

        zip_path = os.path.join(tmpdir, f"export_{body.format}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for arc, real in produced:
                z.write(real, arc)
        background.add_task(_cleanup, tmpdir)
        return FileResponse(zip_path, media_type="application/zip",
                            filename=f"export_{body.format}.zip", background=background)
    except HTTPException:
        _cleanup(tmpdir)
        raise
    except Exception as e:
        _cleanup(tmpdir)
        raise HTTPException(status_code=500, detail=f"Export failed: {e!r}")
