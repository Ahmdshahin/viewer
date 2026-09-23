"""Point-layer-only Data Processor router.

Mirrors the main ``processor`` wizard but handles exactly one layer: the
Point geometry imported into a dedicated GeoPackage, then migrated into the
``mudryia`` PostGIS point table. The point tool keeps its own input/output
directories, Done archive, conflicts log, and progress state so it never
touches the main pipeline's files.

Endpoints (prefix /api/v1/point):
  - progress / scan / run / browse
  - conflicts (dismiss / clear), folder delete, duplicate resolve, DB clear
  - migrate status / history / run (mudryia)
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import os
import json
import sys
import shutil
import traceback
from datetime import datetime
import subprocess

from app.api import deps as _deps
from app.api.processor import _actor, _audit, _read_conflicts, _write_conflicts, _opt_scheme, BASE_DIR
from app.api.migrate import POINT_SQL, _connect

# Ensure project root is in sys path to import the pipeline (location-independent)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from geospatial_pipeline import PointOnlyPipeline

router = APIRouter()

# Point tool defaults: fully separated from the main pipeline.
DEFAULT_INPUT_DIR = r"D:\Systems\Point_Files"
DEFAULT_OUTPUT_GPKG = os.path.join(BASE_DIR, "Point_Database.gpkg")
DEFAULT_DONE_DIR = os.path.join(BASE_DIR, "Point_Done")
DEFAULT_CONFLICTS = os.path.join(BASE_DIR, "point_conflicts.json")
POINT_POSTGIS_TABLE = "mudryia"
GPKG_LAYER = "Point"

# Global progress state (independent from the main pipeline's).
point_pipeline_progress = {
    "status": "idle",  # "idle", "running", "error", "completed"
    "total": 0,
    "processed": 0,
    "current_folder": "",
    "percentage": 0,
    "error_detail": "",
    "logs": [],
}


class RunPipelineRequest(BaseModel):
    input_path: Optional[str] = None
    output_gpkg: Optional[str] = None
    done_dir: Optional[str] = None
    conflicts_file: Optional[str] = None


@router.get("/progress")
async def get_progress():
    return point_pipeline_progress


def update_progress(processed, total, current_folder):
    global point_pipeline_progress
    point_pipeline_progress["processed"] = processed
    point_pipeline_progress["total"] = total
    point_pipeline_progress["current_folder"] = current_folder

    timestamp = datetime.now().strftime("%H:%M:%S")
    log_msg = f"[{timestamp}] Processing {current_folder}..."
    if not point_pipeline_progress["logs"] or point_pipeline_progress["logs"][-1] != log_msg:
        point_pipeline_progress["logs"].append(log_msg)
        if len(point_pipeline_progress["logs"]) > 100:
            point_pipeline_progress["logs"].pop(0)

    if total > 0:
        point_pipeline_progress["percentage"] = round((processed / total) * 100)
    else:
        point_pipeline_progress["percentage"] = 0


def background_point_worker(input_dir, done_dir, conflicts_file, output_gpkg):
    global point_pipeline_progress
    try:
        point_pipeline_progress["status"] = "running"
        point_pipeline_progress["processed"] = 0
        point_pipeline_progress["total"] = 0
        point_pipeline_progress["percentage"] = 0
        point_pipeline_progress["current_folder"] = "Initializing..."
        point_pipeline_progress["error_detail"] = ""
        point_pipeline_progress["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] Point pipeline started..."]

        pipeline = PointOnlyPipeline(
            input_dir, done_dir, conflicts_file, output_gpkg,
            progress_callback=update_progress,
        )
        pipeline.process_all()

        point_pipeline_progress["status"] = "completed"
        point_pipeline_progress["current_folder"] = "All folders processed!"
        point_pipeline_progress["percentage"] = 100
        point_pipeline_progress["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Point pipeline execution completed successfully!")
    except Exception as e:
        traceback.print_exc()
        point_pipeline_progress["status"] = "error"
        point_pipeline_progress["error_detail"] = repr(e)
        point_pipeline_progress["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {repr(e)}")


@router.get("/scan")
def scan_directory(
    input_path: Optional[str] = Query(None),
    conflicts_file: Optional[str] = Query(None),
    done_dir: Optional[str] = Query(None),
):
    try:
        current_input_dir = input_path if input_path else DEFAULT_INPUT_DIR
        current_conflicts = conflicts_file if conflicts_file else DEFAULT_CONFLICTS
        current_done_dir = done_dir if done_dir else DEFAULT_DONE_DIR

        if not os.path.exists(current_input_dir):
            return {
                "total_pending": 0,
                "pending_folders": [],
                "total_done": 0,
                "done_folders": [],
                "total_conflicts": 0,
                "conflicts": [],
                "error": f"Directory {current_input_dir} not found.",
            }

        folders = [f for f in os.listdir(current_input_dir) if os.path.isdir(os.path.join(current_input_dir, f))]

        done_folders = []
        if os.path.exists(current_done_dir):
            done_folders = sorted([f for f in os.listdir(current_done_dir) if os.path.isdir(os.path.join(current_done_dir, f))])

        conflicts = []
        if os.path.exists(current_conflicts):
            try:
                with open(current_conflicts, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    conflicts = loaded if isinstance(loaded, list) else []
            except Exception:
                pass

        current_real = os.path.normcase(os.path.realpath(current_input_dir))
        visible = []
        for c in conflicts:
            if not isinstance(c, dict):
                continue
            if not os.path.isdir(os.path.join(current_input_dir, c.get("folder", ""))):
                continue
            src = c.get("source")
            if src:
                try:
                    match = os.path.normcase(os.path.realpath(src)) == current_real
                except Exception:
                    match = src == current_input_dir
                if match:
                    visible.append(c)
            else:
                visible.append(c)
        conflicts = visible

        return {
            "total_pending": len(folders),
            "pending_folders": folders[:100],
            "total_done": len(done_folders),
            "done_folders": done_folders[:500],
            "total_conflicts": len(conflicts),
            "conflicts": conflicts,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/run")
def run_pipeline(request: RunPipelineRequest, background_tasks: BackgroundTasks):
    global point_pipeline_progress
    if point_pipeline_progress["status"] == "running":
        raise HTTPException(status_code=400, detail="Point pipeline is already running")

    try:
        current_input_dir = request.input_path if request.input_path else DEFAULT_INPUT_DIR
        done_dir = request.done_dir if request.done_dir else DEFAULT_DONE_DIR
        conflicts_file = request.conflicts_file if request.conflicts_file else DEFAULT_CONFLICTS
        output_gpkg = request.output_gpkg if request.output_gpkg else DEFAULT_OUTPUT_GPKG

        if not os.path.exists(current_input_dir):
            raise Exception(f"Input directory does not exist: {current_input_dir}")

        background_tasks.add_task(background_point_worker, current_input_dir, done_dir, conflicts_file, output_gpkg)
        return {"message": "Point pipeline started in background."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


@router.get("/browse")
def browse_path(type: str = Query("folder"), title: str = Query("Select Path"), default_ext: str = Query("*.json")):
    try:
        import tempfile
        script_path = os.path.join(tempfile.gettempdir(), "tk_browse_point.py")

        if type == "folder":
            tk_code = f'''import tkinter as tk
from tkinter import filedialog
import sys
root = tk.Tk()
root.attributes('-topmost', True)
root.withdraw()
path = filedialog.askdirectory(title="{title}")
print(path)
'''
        elif type == "save_file":
            tk_code = f'''import tkinter as tk
from tkinter import filedialog
import sys
root = tk.Tk()
root.attributes('-topmost', True)
root.withdraw()
path = filedialog.asksaveasfilename(title="{title}", defaultextension="{default_ext}")
print(path)
'''
        else:
            tk_code = f'''import tkinter as tk
from tkinter import filedialog
import sys
root = tk.Tk()
root.attributes('-topmost', True)
root.withdraw()
path = filedialog.askopenfilename(title="{title}")
print(path)
'''

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(tk_code)

        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        selected_path = result.stdout.strip()

        return {"path": selected_path}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


class DismissConflictRequest(BaseModel):
    folder: str
    reason: Optional[str] = None


@router.delete("/conflicts")
def dismiss_conflict(request: DismissConflictRequest, conflicts_file: Optional[str] = Query(None),
                     db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Dismiss (remove) a conflict entry from the point log without touching any folders."""
    try:
        current_conflicts = conflicts_file if conflicts_file else DEFAULT_CONFLICTS
        entries = _read_conflicts(current_conflicts)
        before = len(entries)
        if request.reason:
            entries = [e for e in entries if not (e.get("folder") == request.folder and e.get("reason") == request.reason)]
        else:
            entries = [e for e in entries if e.get("folder") != request.folder]
        _write_conflicts(current_conflicts, entries)
        uid, uname = _actor(db, token)
        _audit(db, "point_conflicts", "DISMISS", uname, uid, {"folder": request.folder, "reason": request.reason})
        return {"dismissed": before - len(entries), "remaining": len(entries)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


class ClearConflictsRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/conflicts/clear")
def clear_conflicts(request: ClearConflictsRequest = None, conflicts_file: Optional[str] = Query(None),
                    db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Dismiss point conflict entries — all of them, or only one problem group via reason."""
    try:
        current_conflicts = conflicts_file if conflicts_file else DEFAULT_CONFLICTS
        entries = _read_conflicts(current_conflicts)
        uid, uname = _actor(db, token)
        if request is not None and request.reason:
            remaining = [e for e in entries if e.get("reason") != request.reason]
            dismissed = len(entries) - len(remaining)
            _write_conflicts(current_conflicts, remaining)
            _audit(db, "point_conflicts", "DISMISS_GROUP", uname, uid, {"reason": request.reason, "dismissed": dismissed})
            return {"dismissed": dismissed, "remaining": len(remaining)}
        _write_conflicts(current_conflicts, [])
        _audit(db, "point_conflicts", "DISMISS_ALL", uname, uid, {"dismissed": len(entries)})
        return {"dismissed": len(entries), "remaining": 0}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


@router.delete("/folder")
def delete_input_folder(folder_name: str = Query(...), input_path: Optional[str] = Query(None),
                        conflicts_file: Optional[str] = Query(None),
                        db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Permanently delete an input folder and purge its stale point conflict entries."""
    try:
        current_input_dir = input_path if input_path else DEFAULT_INPUT_DIR
        current_conflicts = conflicts_file if conflicts_file else DEFAULT_CONFLICTS
        base = os.path.realpath(current_input_dir)
        target = os.path.realpath(os.path.join(base, folder_name))
        if os.path.dirname(target) != base or not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Invalid folder name.")
        shutil.rmtree(target)
        entries = _read_conflicts(current_conflicts)
        remaining = [e for e in entries if e.get("folder") != folder_name]
        if len(remaining) != len(entries):
            _write_conflicts(current_conflicts, remaining)
        uid, uname = _actor(db, token)
        _audit(db, "point_input_folders", "DELETE_FOLDER", uname, uid, {"folder": folder_name})
        return {"deleted": folder_name, "remaining_conflicts": len(remaining)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


class ResolveDuplicateRequest(BaseModel):
    folder: str
    mode: str = "replace"  # "replace" | "dismiss"
    input_path: Optional[str] = None
    output_gpkg: Optional[str] = None
    done_dir: Optional[str] = None
    conflicts_file: Optional[str] = None


@router.post("/duplicates/resolve")
def resolve_duplicate(request: ResolveDuplicateRequest,
                      db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Resolve a duplicate-request conflict for one folder in the point pipeline.

    - "dismiss": keep the point database as-is, just drop the conflict entry.
    - "replace": delete the old Point rows for this request number from the
      GPKG, then import this folder's point files instead (append + archive).
    """
    try:
        current_input_dir = request.input_path if request.input_path else DEFAULT_INPUT_DIR
        done_dir = request.done_dir if request.done_dir else DEFAULT_DONE_DIR
        current_conflicts = request.conflicts_file if request.conflicts_file else DEFAULT_CONFLICTS
        output_gpkg = request.output_gpkg if request.output_gpkg else DEFAULT_OUTPUT_GPKG

        base = os.path.realpath(current_input_dir)
        target = os.path.realpath(os.path.join(base, request.folder))
        if os.path.dirname(target) != base or not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Invalid folder name.")

        if ' - ' in request.folder:
            req_number = request.folder.split(' - ', 1)[0].strip()
        else:
            req_number = request.folder.strip()

        entries = _read_conflicts(current_conflicts)
        remaining = [e for e in entries if e.get("folder") != request.folder]
        _write_conflicts(current_conflicts, remaining)

        if request.mode == "dismiss":
            uid, uname = _actor(db, token)
            _audit(db, "point", "RESOLVE_DISMISS", uname, uid,
                   {"folder": request.folder, "req_number": req_number})
            return {"action": "dismissed", "folder": request.folder,
                    "req_number": req_number, "remaining_conflicts": len(remaining)}

        if request.mode != "replace":
            raise HTTPException(status_code=400, detail="mode must be 'replace' or 'dismiss'.")

        import geopandas as gpd
        import pyogrio

        # 1. Delete old Point rows for this request number from the GPKG layer
        deleted = 0
        if os.path.exists(output_gpkg):
            try:
                gdf = gpd.read_file(output_gpkg, layer=GPKG_LAYER, engine="pyogrio")
                if gdf is not None and "Req_Number" in gdf.columns:
                    mask = gdf["Req_Number"].astype(str).str.strip() == req_number
                    deleted = int(mask.sum())
                    if deleted:
                        gdf.loc[~mask].to_file(output_gpkg, layer=GPKG_LAYER, driver="GPKG", mode="w")
            except Exception:
                pass

        # 2. Import this folder's point files (append to GPKG + archive to Done).
        pipeline = PointOnlyPipeline(current_input_dir, done_dir, current_conflicts, output_gpkg)
        pipeline.existing_req_numbers = pipeline.load_existing_req_numbers()
        try:
            pipeline.process_folder(request.folder, target)
        except Exception as import_err:
            try:
                entries = _read_conflicts(current_conflicts)
                entries.append({"folder": request.folder,
                                "reason": f"Replace failed, retry needed: {import_err!r}",
                                "source": current_input_dir})
                _write_conflicts(current_conflicts, entries)
            except Exception:
                pass
            raise
        pipeline.save_conflicts()

        final = _read_conflicts(current_conflicts)
        uid, uname = _actor(db, token)
        _audit(db, "point", "RESOLVE_REPLACE", uname, uid,
               {"folder": request.folder, "req_number": req_number, "deleted_rows": deleted})
        return {"action": "replaced", "folder": request.folder,
                "req_number": req_number, "deleted_rows": deleted,
                "remaining_conflicts": len(final)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


@router.post("/database/clear")
def clear_database(output_gpkg: Optional[str] = Query(None),
                   db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Danger zone: delete ALL Point rows by removing the point GeoPackage file."""
    try:
        gpkg = output_gpkg if output_gpkg else DEFAULT_OUTPUT_GPKG
        if not os.path.exists(gpkg):
            return {"emptied": False, "removed_features": {}, "total_removed": 0,
                    "message": "Database file does not exist."}
        removed = {}
        try:
            import pyogrio
            meta = pyogrio.read_info(gpkg, layer=GPKG_LAYER)
            removed[GPKG_LAYER] = int(meta.get("features", meta.get("feature_count", 0)))
        except Exception:
            removed[GPKG_LAYER] = -1
        os.remove(gpkg)
        uid, uname = _actor(db, token)
        _audit(db, "database", "CLEAR_POINT", uname, uid,
               {"file": os.path.basename(gpkg), "removed_features": removed})
        return {"emptied": True, "removed_features": removed,
                "total_removed": sum(v for v in removed.values() if v > 0),
                "backup": None}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


# ---- migrate: GPKG Point layer -> mudryia PostGIS table ----

class MigrateRunRequest(BaseModel):
    output_gpkg: Optional[str] = None


@router.get("/migrate/status")
def migrate_status(output_gpkg: Optional[str] = Query(None)):
    """Show what is available to migrate (GPKG Point) vs what is live (mudryia)."""
    gpkg = output_gpkg if output_gpkg else DEFAULT_OUTPUT_GPKG
    result: Dict = {"gpkg_path": gpkg, "gpkg_exists": os.path.exists(gpkg),
                    "gpkg_layers": {}, "postgis": {}}
    if os.path.exists(gpkg):
        try:
            import pyogrio
            meta = pyogrio.read_info(gpkg, layer=GPKG_LAYER)
            result["gpkg_layers"][GPKG_LAYER] = int(meta.get("features", meta.get("feature_count", 0)))
        except Exception:
            result["gpkg_layers"][GPKG_LAYER] = 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{POINT_POSTGIS_TABLE}";')
            result["postgis"][POINT_POSTGIS_TABLE] = int(cur.fetchone()[0])
    finally:
        conn.close()
    return result


@router.get("/migrate/history")
def migrate_history(limit: int = Query(50, ge=1, le=200)):
    """Recent point migrations with the user who ran each one (newest first)."""
    import psycopg2.extras
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, table_name, action, user_id, username, created_at, new_values
                   FROM audit_trail WHERE action = 'MIGRATE_POINT'
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


@router.post("/migrate/run")
def migrate_run(request: MigrateRunRequest, current_user=Depends(_deps.get_current_active_editor)):
    """Migrate the point GPKG layer into the mudryia PostGIS table.

    Only users with admin/editor role may run this; every layer migrated is
    recorded in audit_trail under the calling user's name. Requests already
    present in mudryia are skipped.
    """
    gpkg = request.output_gpkg if request.output_gpkg else DEFAULT_OUTPUT_GPKG
    if not os.path.exists(gpkg):
        raise HTTPException(status_code=400, detail=f"Database file not found: {gpkg}. Run the point pipeline first.")

    imported = gpd = None
    try:
        import geopandas as gpd
    except Exception:
        gpd = None

    migrated = 0
    skipped = 0
    skipped_reqs = []

    conn = _connect()
    try:
        with conn.cursor() as cur:
            try:
                if gpd is None:
                    raise RuntimeError("geopandas unavailable")
                gdf = gpd.read_file(gpkg, layer=GPKG_LAYER, engine="pyogrio")
            except Exception:
                migrated = 0
                skipped = 0
                skipped_reqs = []
            else:
                if gdf is None or gdf.empty:
                    migrated = 0
                    skipped = 0
                    skipped_reqs = []
                else:
                    # Normalize to EPSG:32636 planar meters
                    try:
                        if gdf.crs is None:
                            gdf = gdf.set_crs(epsg=32636)
                        elif gdf.crs.to_epsg() != 32636:
                            gdf = gdf.to_crs(epsg=32636)
                    except Exception:
                        pass
                    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]

                    cur.execute(f'SELECT DISTINCT "Req_Number" FROM {POINT_POSTGIS_TABLE};')
                    existing = {r[0] for r in cur.fetchall() if r[0]}

                    records = []
                    for _, row in gdf.iterrows():
                        req = str(row["Req_Number"]).strip() if row.get("Req_Number") is not None else None
                        if req and req in existing:
                            skipped += 1
                            continue
                        owner = str(row["Owner_Name"]).strip() if row.get("Owner_Name") is not None else None
                        ltype = str(row["Layer_Type"]).strip() if row.get("Layer_Type") is not None else GPKG_LAYER
                        records.append((req, owner, ltype, row.geometry.wkt, current_user.username))

                    if records:
                        sql = POINT_SQL.format(table=POINT_POSTGIS_TABLE)
                        inserted = None
                        try:
                            import psycopg2.extras
                            inserted = psycopg2.extras.execute_values(cur, sql, records,
                                                                      template="(%s, %s, %s, %s, %s)", fetch=True)
                        except Exception as e:
                            raise HTTPException(status_code=500, detail=f"Point migration failed: {e!r}")
                        migrated = len(inserted) if inserted is not None else 0

                    seen = set()
                    skip_list = []
                    for _, row in gdf.iterrows():
                        req = str(row["Req_Number"]).strip() if row.get("Req_Number") is not None else None
                        if req and req in existing and not (req in seen or seen.add(req)):
                            skip_list.append(req)
                    skipped_reqs = skip_list[:500]

                    meta = {
                        "source_file": os.path.basename(gpkg),
                        "source_layer": GPKG_LAYER,
                        "target_table": POINT_POSTGIS_TABLE,
                        "features_migrated": migrated,
                        "requests_skipped": len(skip_list),
                        "crs_source": "EPSG:32636",
                        "crs_target": "EPSG:32636",
                        "status": "completed",
                    }
                    cur.execute(
                        """INSERT INTO audit_trail
                           (table_name, record_id, action, old_values, new_values, user_id, username, created_at, timestamp)
                           VALUES (%s, NULL, 'MIGRATE_POINT', NULL, %s, %s, %s, NOW(), NOW()) RETURNING id;""",
                        (POINT_POSTGIS_TABLE, json.dumps(meta, ensure_ascii=False), current_user.id, current_user.username),
                    )
                    cur.fetchone()
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
            "skipped_requests": skipped_reqs,
            "migrated_by": current_user.username,
            "table": POINT_POSTGIS_TABLE}