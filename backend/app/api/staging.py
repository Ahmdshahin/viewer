"""Browser-upload staging for the processor pipelines.

Remote browsers cannot use the old tkinter server-side file dialogs, so
clients upload input folders through the browser into a per-session staging
directory on the server. The pipelines then run against the staged copy:

  POST /staging/init                       -> {session_id, input_dir, ...}
  POST /staging/upload (multipart)         -> stores one file, streamed
  GET  /staging/list?session_id=           -> staged tree + sizes
  DELETE /staging/session?session_id=      -> cleanup
"""

import os
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api import deps
from app.db.models import User

router = APIRouter()

STAGING_ROOT = os.path.abspath(
    os.getenv("STAGING_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "staging"))
)
MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GiB per file
MAX_SESSION_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB per session
ALLOWED_EXTS = {
    ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qpj", ".shp.xml",
    ".csv", ".xlsx", ".xls", ".json", ".geojson",
}


def _session_dir(session_id: str) -> str:
    if not session_id or len(session_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid session id")
    if any(c not in "0123456789abcdefABCDEF-_" for c in session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    path = os.path.abspath(os.path.join(STAGING_ROOT, session_id))
    if os.path.commonpath([path, STAGING_ROOT]) != STAGING_ROOT:
        raise HTTPException(status_code=400, detail="Invalid session id")
    return path


def _safe_rel(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").strip().lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p for p in parts):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return "/".join(parts)


def _session_size(base: str) -> int:
    total = 0
    for dp, _, fns in os.walk(base):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


@router.post("/init")
def init_session(current_user: User = Depends(deps.get_current_active_editor)):
    sid = uuid.uuid4().hex
    base = _session_dir(sid)
    os.makedirs(os.path.join(base, "input"), exist_ok=True)
    os.makedirs(os.path.join(base, "done"), exist_ok=True)
    return {
        "session_id": sid,
        "input_dir": os.path.join(base, "input"),
        "output_gpkg": os.path.join(base, "output.gpkg"),
        "done_dir": os.path.join(base, "done"),
        "conflicts_file": os.path.join(base, "conflicts.json"),
    }


@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    relative_path: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_editor),
):
    base = _session_dir(session_id)
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="Upload session not found")
    rel = _safe_rel(relative_path)
    if rel == "input" or rel.startswith("input/"):
        rel = rel[len("input"):].lstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail="Invalid file path")
    input_root = os.path.abspath(os.path.join(base, "input"))
    dest = os.path.abspath(os.path.join(input_root, rel))
    if os.path.commonpath([dest, input_root]) != input_root:
        raise HTTPException(status_code=400, detail="Invalid file path")
    lowered = rel.lower()
    ext = ".shp.xml" if lowered.endswith(".shp.xml") else os.path.splitext(rel)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {ext or '(none)'} — upload shapefile parts, CSV, Excel, JSON or GeoJSON")
    quota_left = MAX_SESSION_BYTES - _session_size(base)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES or size > quota_left:
                    raise HTTPException(status_code=413, detail="Upload quota exceeded (1 GiB/file, 5 GiB/session)")
                out.write(chunk)
    except HTTPException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return {"path": rel, "size": size}


@router.get("/list")
def list_session(
    session_id: str,
    current_user: User = Depends(deps.get_current_user),
):
    base = _session_dir(session_id)
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="Upload session not found")
    input_root = os.path.join(base, "input")
    files = []
    total = 0
    for dp, _, fns in os.walk(input_root):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            total += sz
            files.append({"path": os.path.relpath(fp, input_root).replace("\\", "/"), "size": sz})
    files.sort(key=lambda x: x["path"])
    return {
        "session_id": session_id,
        "files": files[:2000],
        "truncated": len(files) > 2000,
        "total_bytes": total,
        "file_count": len(files),
    }


@router.delete("/session")
def delete_session(
    session_id: str,
    current_user: User = Depends(deps.get_current_active_editor),
):
    base = _session_dir(session_id)
    shutil.rmtree(base, ignore_errors=True)
    return {"deleted": session_id}
