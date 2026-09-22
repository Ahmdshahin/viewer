from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
import os
import json
import sys
import shutil
import traceback
from datetime import datetime
import subprocess

from app.api import deps as _deps
from app.db import models as _models

# Ensure project root is in sys path to import the pipeline (location-independent)
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from geospatial_pipeline import GeospatialDataPipeline

router = APIRouter()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Inputs live outside the app dir; fall back here when the client sends none.
DEFAULT_INPUT_DIR = r"D:\Systems\SHP_Files(2)"

# Optional bearer auth: destructive endpoints stay open (wizard compatibility)
# but attribute the acting user in audit_trail whenever a token is provided.
_opt_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _actor(db: Session, token: Optional[str]):
    """(user_id, username) from an optional bearer token, else system fallback."""
    try:
        if token:
            from app.core.security import decode_access_token
            data = decode_access_token(token)
            if data and data.get("username"):
                u = db.query(_models.User).filter(_models.User.username == data["username"]).first()
                if u:
                    return u.id, u.username
    except Exception:
        pass
    return None, "system"


def _audit(db: Session, table_name: str, action: str, username: str, user_id, detail: dict):
    """Best-effort immutable audit row; never breaks the calling operation."""
    try:
        db.execute(
            text("INSERT INTO audit_trail (table_name, record_id, action, old_values, new_values, "
                 "user_id, username, created_at, timestamp) "
                 "VALUES (:t, NULL, :a, NULL, :n, :u, :un, NOW(), NOW())"),
            {"t": table_name, "a": action, "n": json.dumps(detail or {}, ensure_ascii=False),
             "u": user_id, "un": username},
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

# Global progress state
pipeline_progress = {
    "status": "idle", # "idle", "running", "error", "completed"
    "total": 0,
    "processed": 0,
    "current_folder": "",
    "percentage": 0,
    "error_detail": "",
    "logs": []
}

class RunPipelineRequest(BaseModel):
    input_path: Optional[str] = None
    output_gpkg: Optional[str] = None
    done_dir: Optional[str] = None
    conflicts_file: Optional[str] = None

@router.get("/progress")
async def get_progress():
    return pipeline_progress

def update_progress(processed, total, current_folder):
    global pipeline_progress
    pipeline_progress["processed"] = processed
    pipeline_progress["total"] = total
    pipeline_progress["current_folder"] = current_folder
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_msg = f"[{timestamp}] Processing {current_folder}..."
    if not pipeline_progress["logs"] or pipeline_progress["logs"][-1] != log_msg:
        pipeline_progress["logs"].append(log_msg)
        if len(pipeline_progress["logs"]) > 100:
            pipeline_progress["logs"].pop(0)

    if total > 0:
        pipeline_progress["percentage"] = round((processed / total) * 100)
    else:
        pipeline_progress["percentage"] = 0

def background_pipeline_worker(input_dir, done_dir, conflicts_file, output_gpkg):
    global pipeline_progress
    try:
        pipeline_progress["status"] = "running"
        pipeline_progress["processed"] = 0
        pipeline_progress["total"] = 0
        pipeline_progress["percentage"] = 0
        pipeline_progress["current_folder"] = "Initializing..."
        pipeline_progress["error_detail"] = ""
        pipeline_progress["logs"] = [f"[{datetime.now().strftime('%H:%M:%S')}] Pipeline started..."]
        
        pipeline = GeospatialDataPipeline(
            input_dir, done_dir, conflicts_file, output_gpkg, 
            progress_callback=update_progress
        )
        pipeline.process_all()
        
        pipeline_progress["status"] = "completed"
        pipeline_progress["current_folder"] = "All folders processed!"
        pipeline_progress["percentage"] = 100
        pipeline_progress["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Pipeline execution completed successfully!")
    except Exception as e:
        traceback.print_exc()
        pipeline_progress["status"] = "error"
        pipeline_progress["error_detail"] = repr(e)
        pipeline_progress["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {repr(e)}")

@router.get("/scan")
def scan_directory(
    input_path: Optional[str] = Query(None),
    conflicts_file: Optional[str] = Query(None),
    done_dir: Optional[str] = Query(None)
):
    try:
        current_input_dir = input_path if input_path else DEFAULT_INPUT_DIR
        current_conflicts = conflicts_file if conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
        current_done_dir = done_dir if done_dir else os.path.join(BASE_DIR, "Done")
        
        if not os.path.exists(current_input_dir):
            return {
                "total_pending": 0,
                "pending_folders": [],
                "total_done": 0,
                "done_folders": [],
                "total_conflicts": 0,
                "conflicts": [],
                "error": f"Directory {current_input_dir} not found."
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
            except:
                pass

        # Show only conflicts belonging to the scanned input directory and
        # whose folder is still there (stale entries for deleted folders hide).
        # New entries carry their "source" input dir; legacy entries without
        # one are shown only if their folder still exists in this input.
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
            "conflicts": conflicts
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))

@router.post("/run")
def run_pipeline(request: RunPipelineRequest, background_tasks: BackgroundTasks):
    global pipeline_progress
    if pipeline_progress["status"] == "running":
        raise HTTPException(status_code=400, detail="Pipeline is already running")
        
    try:
        current_input_dir = request.input_path if request.input_path else DEFAULT_INPUT_DIR
        done_dir = request.done_dir if request.done_dir else os.path.join(BASE_DIR, "Done")
        conflicts_file = request.conflicts_file if request.conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
        output_gpkg = request.output_gpkg if request.output_gpkg else os.path.join(BASE_DIR, "Unified_Database.gpkg")

        if not os.path.exists(current_input_dir):
             raise Exception(f"Input directory does not exist: {current_input_dir}")

        background_tasks.add_task(background_pipeline_worker, current_input_dir, done_dir, conflicts_file, output_gpkg)
        return {"message": "Pipeline started in background."}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))

@router.get("/browse")
def browse_path(type: str = Query("folder"), title: str = Query("Select Path"), default_ext: str = Query("*.json")):
    try:
        # We run a small subprocess to pop up the Tkinter dialog 
        # so it doesn't freeze or crash the Uvicorn thread.
        import tempfile
        script_path = os.path.join(tempfile.gettempdir(), "tk_browse.py")
        
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

def _read_conflicts(path):
    """Read the conflicts log. Missing file -> []. Corrupt/unexpected content
    raises so callers never overwrite a file they failed to read."""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"conflicts file is not a list: {path}")
    return data

def _write_conflicts(path, entries):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=4)

@router.delete("/conflicts")
def dismiss_conflict(request: DismissConflictRequest, conflicts_file: Optional[str] = Query(None),
                     db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Dismiss (remove) a conflict entry from the log without touching any folders."""
    try:
        current_conflicts = conflicts_file if conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
        entries = _read_conflicts(current_conflicts)
        before = len(entries)
        if request.reason:
            entries = [e for e in entries if not (e.get("folder") == request.folder and e.get("reason") == request.reason)]
        else:
            entries = [e for e in entries if e.get("folder") != request.folder]
        _write_conflicts(current_conflicts, entries)
        uid, uname = _actor(db, token)
        _audit(db, "conflicts", "DISMISS", uname, uid, {"folder": request.folder, "reason": request.reason})
        return {"dismissed": before - len(entries), "remaining": len(entries)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))

class ClearConflictsRequest(BaseModel):
    reason: Optional[str] = None

@router.post("/conflicts/clear")
def clear_conflicts(request: ClearConflictsRequest = None, conflicts_file: Optional[str] = Query(None),
                    db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Dismiss conflict entries — all of them, or only one problem group via reason."""
    try:
        current_conflicts = conflicts_file if conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
        entries = _read_conflicts(current_conflicts)
        uid, uname = _actor(db, token)
        if request is not None and request.reason:
            remaining = [e for e in entries if e.get("reason") != request.reason]
            dismissed = len(entries) - len(remaining)
            _write_conflicts(current_conflicts, remaining)
            _audit(db, "conflicts", "DISMISS_GROUP", uname, uid, {"reason": request.reason, "dismissed": dismissed})
            return {"dismissed": dismissed, "remaining": len(remaining)}
        _write_conflicts(current_conflicts, [])
        _audit(db, "conflicts", "DISMISS_ALL", uname, uid, {"dismissed": len(entries)})
        return {"dismissed": len(entries), "remaining": 0}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))

@router.delete("/folder")
def delete_input_folder(folder_name: str = Query(...), input_path: Optional[str] = Query(None), conflicts_file: Optional[str] = Query(None),
                        db: Session = Depends(_deps.get_db), token: Optional[str] = Depends(_opt_scheme)):
    """Permanently delete an input folder (e.g. empty or duplicate) and purge its stale conflict entries.

    Safety: the target must resolve to a directory directly inside the input dir.
    """
    try:
        current_input_dir = input_path if input_path else DEFAULT_INPUT_DIR
        current_conflicts = conflicts_file if conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
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
        _audit(db, "input_folders", "DELETE_FOLDER", uname, uid, {"folder": folder_name})
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
    """Resolve a duplicate-request conflict for one folder.

    - "dismiss": keep the database as-is, just drop the conflict entry.
    - "replace": delete the old rows for this request number from every
      GPKG layer, then import this folder's files instead (append + archive).
    """
    try:
        current_input_dir = request.input_path if request.input_path else DEFAULT_INPUT_DIR
        done_dir = request.done_dir if request.done_dir else os.path.join(BASE_DIR, "Done")
        current_conflicts = request.conflicts_file if request.conflicts_file else os.path.join(BASE_DIR, "conflicts.json")
        output_gpkg = request.output_gpkg if request.output_gpkg else os.path.join(BASE_DIR, "Unified_Database.gpkg")

        base = os.path.realpath(current_input_dir)
        target = os.path.realpath(os.path.join(base, request.folder))
        if os.path.dirname(target) != base or not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="Invalid folder name.")

        if ' - ' in request.folder:
            req_number = request.folder.split(' - ', 1)[0].strip()
        else:
            req_number = request.folder.strip()

        # Purge this folder's conflict entries (both modes)
        entries = _read_conflicts(current_conflicts)
        remaining = [e for e in entries if e.get("folder") != request.folder]
        _write_conflicts(current_conflicts, remaining)

        if request.mode == "dismiss":
            uid, uname = _actor(db, token)
            _audit(db, "cadastral", "RESOLVE_DISMISS", uname, uid,
                   {"folder": request.folder, "req_number": req_number})
            return {"action": "dismissed", "folder": request.folder,
                    "req_number": req_number, "remaining_conflicts": len(remaining)}

        if request.mode != "replace":
            raise HTTPException(status_code=400, detail="mode must be 'replace' or 'dismiss'.")

        import geopandas as gpd
        import pyogrio

        # 1. Delete old rows for this request number from every layer
        deleted = {}
        if os.path.exists(output_gpkg):
            try:
                info = pyogrio.list_layers(output_gpkg)
                if hasattr(info, "columns") and "name" in info.columns:
                    layers = info["name"].tolist()
                else:
                    layers = [row[0] for row in info]
            except Exception:
                layers = ["Land", "Eshghalat", "Point"]
            for layer in layers:
                try:
                    gdf = gpd.read_file(output_gpkg, layer=layer, engine="pyogrio")
                except Exception:
                    continue
                if gdf is None or "Req_Number" not in gdf.columns:
                    continue
                mask = gdf["Req_Number"].astype(str).str.strip() == req_number
                n = int(mask.sum())
                if n:
                    gdf.loc[~mask].to_file(output_gpkg, layer=layer, driver="GPKG", mode="w")
                    deleted[layer] = n

        # 2. Import this folder's files (append to DB + archive to Done).
        # Reload existing numbers AFTER the delete so this request proceeds.
        pipeline = GeospatialDataPipeline(
            current_input_dir, done_dir, current_conflicts, output_gpkg)
        pipeline.existing_req_numbers = pipeline.load_existing_req_numbers()
        try:
            pipeline.process_folder(request.folder, target)
        except Exception as import_err:
            # DB rows for this request were already deleted above: re-log so
            # the folder is not lost (a normal run will pick it up again).
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
        _audit(db, "cadastral", "RESOLVE_REPLACE", uname, uid,
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
    """Danger zone: delete ALL rows by removing the output GeoPackage file.

    No backup is kept. The file is recreated automatically on the next
    pipeline run. Conflicts log and Done archive are left untouched.
    """
    try:
        gpkg = output_gpkg if output_gpkg else os.path.join(BASE_DIR, "Unified_Database.gpkg")
        if not os.path.exists(gpkg):
            return {"emptied": False, "removed_features": {}, "total_removed": 0,
                    "message": "Database file does not exist."}
        removed = {}
        try:
            import pyogrio
            info = pyogrio.list_layers(gpkg)
            if hasattr(info, "columns") and "name" in info.columns:
                names = info["name"].tolist()
            else:
                names = [row[0] for row in info]
            for layer in names:
                try:
                    meta = pyogrio.read_info(gpkg, layer=layer)
                    removed[layer] = int(meta.get("features", meta.get("feature_count", 0)))
                except Exception:
                    removed[layer] = -1
        except Exception:
            pass
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.remove(gpkg)
        uid, uname = _actor(db, token)
        _audit(db, "database", "CLEAR", uname, uid,
               {"file": os.path.basename(gpkg), "removed_features": removed})
        return {"emptied": True, "removed_features": removed,
                "total_removed": sum(v for v in removed.values() if v > 0),
                "backup": None}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))
