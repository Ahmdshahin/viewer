"""Scheduled Postgres backups (admin only).

The schedule lives in backend/backup_settings.json next to db_connection.json,
so it keeps working after a database switch and survives restarts. A daemon
thread started from the app lifespan checks every 20s whether a backup is due
and shells out to pg_dump (-Fc, compressed custom format, .bak extension).

Every finished run writes its outcome back to the settings file and drops a
notification in every active admin's bell.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_current_active_admin
from app.core.config import settings
from app.db.models import Notification, User
from app.db.session import SessionLocal, get_engine

router = APIRouter()

SETTINGS_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backup_settings.json")
)
DEFAULT_FOLDER = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "backups")
)
FILE_SUFFIX = ".bak"
BACKUP_TIMEOUT = 4 * 60 * 60  # seconds

_DEFAULTS = {
    "enabled": False,
    "mode": "daily",            # "daily" | "interval"
    "time": "02:00",            # HH:MM local server time (daily mode)
    "interval_hours": 24,       # interval mode
    "path": DEFAULT_FOLDER,
    "keep_days": 14,            # 0 = keep every file
    "pg_dump_path": None,       # optional explicit pg_dump (e.g. a newer install)
    "next_run": None,
    "last_run": None,
    "last_status": None,        # "ok" | "error"
    "last_file": None,
    "last_size": None,
    "last_message": None,
    "last_trigger": None,
}

_running = threading.Event()
_lock = threading.Lock()


# ---------- settings file ----------

def _load() -> dict:
    import json
    cfg = dict(_DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in _DEFAULTS})
    except Exception:
        pass
    cfg["path"] = os.path.normpath(str(cfg.get("path") or DEFAULT_FOLDER))
    return cfg


def _save(cfg: dict) -> None:
    import json
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)


# ---------- helpers ----------

_dump_versions = {}
_server_versions = {}


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _version_of(text) -> Optional[tuple]:
    m = re.search(r"(\d+)(?:\.(\d+))?", str(text or ""))
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _dump_version(path: str):
    """Return ((major, minor), raw --version text) for a pg_dump binary."""
    if path in _dump_versions:
        return _dump_versions[path]
    ver, raw = None, ""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True,
                             timeout=20, creationflags=_no_window())
        raw = (out.stdout or out.stderr or "").strip()
        ver = _version_of(raw)
        if ver:
            raw = f"{ver[0]}.{ver[1]}"
    except Exception:
        pass
    _dump_versions[path] = (ver, raw)
    return ver, raw


def _pg_dump_candidates() -> List[str]:
    """pg_dump from PATH plus every PostgreSQL install under Program Files."""
    paths = []
    found = shutil.which("pg_dump")
    if found:
        paths.append(found)
    bases = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    for base in bases:
        if not base:
            continue
        pgdir = os.path.join(base, "PostgreSQL")
        if not os.path.isdir(pgdir):
            continue
        try:
            versions = sorted(os.listdir(pgdir), reverse=True)
        except Exception:
            continue
        for v in versions:
            exe = os.path.join(pgdir, v, "bin", "pg_dump.exe")
            if os.path.isfile(exe):
                paths.append(exe)
    out, seen = [], set()
    for p in paths:
        full = os.path.abspath(p)
        key = os.path.normcase(full)
        if key not in seen:
            seen.add(key)
            out.append(full)
    return out


def _server_version():
    """(version tuple, raw string) of the database the app is connected to."""
    key = (settings.POSTGRES_SERVER, settings.POSTGRES_PORT, settings.POSTGRES_DB)
    if key in _server_versions:
        return _server_versions[key]
    raw = None
    try:
        with get_engine().connect() as c:
            raw = c.exec_driver_sql("SHOW server_version").scalar()
    except Exception:
        raw = None
    result = (_version_of(raw), str(raw or "").strip() or None)
    if result[0]:
        _server_versions[key] = result
    return result


def _pick_pg_dump() -> dict:
    """Pick the best pg_dump: newer-or-equal to the server, closest when possible.

    PostgreSQL requires pg_dump to be the same major version or newer than the
    server; a newer pg_dump can always dump an older server.
    """
    cfg = _load()
    override = (cfg.get("pg_dump_path") or "").strip()
    server_ver, server_raw = _server_version()

    candidates = []
    for path in _pg_dump_candidates():
        ver, raw = _dump_version(path)
        candidates.append({"path": path, "version": raw, "major": ver[0] if ver else None})

    chosen = None
    if override:
        resolved = override if os.path.isfile(override) else (shutil.which(override) or override)
        chosen = next((c for c in candidates
                       if os.path.normcase(c["path"]) == os.path.normcase(os.path.abspath(resolved))), None)
        if chosen is None and os.path.isfile(resolved):
            ver, raw = _dump_version(resolved)
            chosen = {"path": os.path.abspath(resolved), "version": raw,
                      "major": ver[0] if ver else None}

    if chosen is None and candidates:
        if server_ver:
            compatible = [c for c in candidates if c["major"] and c["major"] >= server_ver[0]]
            chosen = min(compatible, key=lambda c: c["major"]) if compatible \
                else max(candidates, key=lambda c: c["major"] or 0)
        else:
            chosen = max(candidates, key=lambda c: c["major"] or 0)

    info = {
        "pg_dump": None,
        "pg_dump_version": None,
        "server_version": server_raw,
        "compatible": None,
        "pg_dump_override": override or None,
        "pg_dump_candidates": candidates,
    }
    if chosen:
        info["pg_dump"] = chosen["path"]
        info["pg_dump_version"] = chosen["version"]
        if server_ver and chosen["major"]:
            info["compatible"] = chosen["major"] >= server_ver[0]
    return info



def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _parse_time(value: str):
    hh, _, mm = str(value or "").partition(":")
    hour, minute = int(hh), int(mm or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time must be HH:MM")
    return hour, minute


def _compute_next_run(cfg: dict, now: Optional[datetime] = None) -> Optional[str]:
    now = now or datetime.now()
    if cfg.get("mode") == "interval":
        hours = max(1, min(168, int(cfg.get("interval_hours") or 24)))
        return (now + timedelta(hours=hours)).replace(microsecond=0).isoformat()
    hour, minute = _parse_time(cfg.get("time") or "02:00")
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.isoformat()


def _ensure_folder(path: str) -> str:
    folder = os.path.normpath(os.path.abspath(os.path.expandvars(path or "")))
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot create backup folder: {e}")
    probe = os.path.join(folder, ".write_test")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Backup folder is not writable: {e}")
    return folder


def _notify_admins(title: str, body: str) -> None:
    db = None
    try:
        db = SessionLocal(bind=get_engine())
        admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()  # noqa: E712
        for u in admins:
            db.add(Notification(user_id=u.id, type="backup", title=title[:200], body=body))
        db.commit()
    except Exception as e:
        print(f"backup notification skipped: {e}")
    finally:
        try:
            if db is not None:
                db.close()
        except Exception:
            pass


def _human_size(n: Optional[int]) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.0f} {units[i]}" if i == 0 else f"{v:.1f} {units[i]}"


def _list_files(folder: str) -> List[dict]:
    out = []
    try:
        for name in os.listdir(folder):
            if not name.lower().endswith(FILE_SUFFIX):
                continue
            full = os.path.join(folder, name)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            out.append({
                "name": name,
                "size": int(st.st_size),
                "mtime": datetime.fromtimestamp(st.st_mtime).replace(microsecond=0).isoformat(),
            })
    except Exception:
        return []
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out


def _cleanup(folder: str, keep_days: int) -> List[str]:
    """Delete .bak files older than keep_days (0 keeps everything)."""
    if not keep_days or keep_days <= 0:
        return []
    cutoff = datetime.now() - timedelta(days=int(keep_days))
    removed = []
    for f in _list_files(folder):
        try:
            if datetime.fromisoformat(f["mtime"]) < cutoff:
                os.remove(os.path.join(folder, f["name"]))
                removed.append(f["name"])
        except Exception:
            continue
    return removed


# ---------- the backup itself ----------

def _run_backup(trigger: str) -> None:
    cfg = _load()
    started = datetime.now().replace(microsecond=0)
    folder = cfg["path"]
    status, message, saved_name, saved_size = "error", "", None, None
    try:
        _ensure_folder(folder)
        pick = _pick_pg_dump()
        pg_dump = pick.get("pg_dump")
        if not pg_dump:
            raise RuntimeError("pg_dump was not found — install PostgreSQL client tools or add pg_dump to PATH")
        if pick.get("compatible") is False:
            raise RuntimeError(
                f"pg_dump {pick.get('pg_dump_version')} is older than the server "
                f"({pick.get('server_version')}) — install matching/newer PostgreSQL client tools "
                f"or set the pg_dump path explicitly"
            )
        stamp = started.strftime("%Y%m%d_%H%M%S")
        db = settings.POSTGRES_DB or "database"
        saved_name = f"{db}_{stamp}{FILE_SUFFIX}"
        target = os.path.join(folder, saved_name)
        cmd = [
            pg_dump,
            "--host", str(settings.POSTGRES_SERVER),
            "--port", str(settings.POSTGRES_PORT),
            "--username", str(settings.POSTGRES_USER),
            "--dbname", str(settings.POSTGRES_DB),
            "--format=custom",
            "--compress=6",
            "--file", target,
        ]
        env = os.environ.copy()
        env["PGPASSWORD"] = str(settings.POSTGRES_PASSWORD or "")
        env["PGCLIENTENCODING"] = "UTF8"
        flags = _no_window()
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=BACKUP_TIMEOUT, creationflags=flags,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "pg_dump failed").strip()[:400])
        saved_size = os.path.getsize(target)
        status = "ok"
        message = f"{saved_name} ({_human_size(saved_size)})"
        removed = _cleanup(folder, int(cfg.get("keep_days") or 0))
        if removed:
            message += f" — cleaned {len(removed)} old file(s)"
    except Exception as e:
        message = str(e)[:400]
        if saved_name:
            try:
                partial = os.path.join(folder, saved_name)
                if os.path.isfile(partial):
                    os.remove(partial)
            except Exception:
                pass
            saved_name, saved_size = None, None

    finished = datetime.now().replace(microsecond=0)

    # Roll the schedule forward from "now" (manual runs included).
    cfg = _load()
    cfg.update({
        "last_run": finished.isoformat(),
        "last_status": status,
        "last_file": saved_name,
        "last_size": saved_size,
        "last_message": message,
        "last_trigger": trigger,
    })
    now = finished
    if cfg.get("enabled"):
        cfg["next_run"] = _compute_next_run(cfg, now)
    else:
        cfg["next_run"] = None
    with _lock:
        _save(cfg)

    if status == "ok":
        _notify_admins(
            "نسخة احتياطية ناجحة",
            f"تم إنشاء نسخة احتياطية لقاعدة البيانات «{settings.POSTGRES_DB}» في {finished.strftime('%Y-%m-%d %H:%M')}.\n"
            f"الملف: {saved_name}\nالحجم: {_human_size(saved_size)}\nالمسار: {folder}",
        )
    else:
        _notify_admins(
            "فشل النسخ الاحتياطي",
            f"تعذّر إنشاء نسخة احتياطية لقاعدة البيانات «{settings.POSTGRES_DB}» في {finished.strftime('%Y-%m-%d %H:%M')}.\n"
            f"السبب: {message}",
        )
    print(f"backup {trigger}: {status} — {message}")


def _start_backup(trigger: str) -> bool:
    if _running.is_set():
        return False

    def worker():
        _running.set()
        try:
            _run_backup(trigger)
        except Exception as e:  # never let the thread die silently
            print(f"backup crashed: {e}")
        finally:
            _running.clear()

    threading.Thread(target=worker, name=f"backup-{trigger}", daemon=True).start()
    return True


# ---------- scheduler ----------

_scheduler_started = False


def _scheduler_loop() -> None:
    time.sleep(5)
    while True:
        try:
            cfg = _load()
            due = _parse_dt(cfg.get("next_run"))
            if cfg.get("enabled") and due and datetime.now() >= due and not _running.is_set():
                _start_backup("schedule")
        except Exception as e:
            print(f"backup scheduler: {e}")
        time.sleep(20)


def start_scheduler() -> None:
    """Start the due-check thread once per process (called from lifespan)."""
    global _scheduler_started
    with _lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    threading.Thread(target=_scheduler_loop, name="backup-scheduler", daemon=True).start()


# ---------- API ----------

class BackupConfigIn(BaseModel):
    enabled: bool = False
    mode: str = "daily"
    time: str = "02:00"
    interval_hours: int = 24
    path: str
    keep_days: int = 14
    pg_dump_path: Optional[str] = None


def _state() -> dict:
    cfg = _load()
    files = _list_files(cfg["path"])
    pick = _pick_pg_dump()
    return {
        "config": cfg,
        "running": _running.is_set(),
        "pg_dump": pick["pg_dump"],
        "pg_dump_version": pick["pg_dump_version"],
        "pg_dump_override": pick["pg_dump_override"],
        "pg_dump_compatible": pick["compatible"],
        "pg_dump_candidates": pick["pg_dump_candidates"],
        "server_version": pick["server_version"],
        "folder_exists": os.path.isdir(cfg["path"]),
        "files": files[:100],
        "total_files": len(files),
        "total_size": sum(f["size"] for f in files),
        "server_time": datetime.now().replace(microsecond=0).isoformat(),
    }


@router.get("/backup")
def get_backup(current_user: User = Depends(get_current_active_admin)):
    """Schedule, last result, and the .bak files already on disk."""
    return _state()


@router.put("/backup")
def save_backup(body: BackupConfigIn,
                current_user: User = Depends(get_current_active_admin)):
    """Validate and store the schedule; recomputes the next run time."""
    if body.mode not in ("daily", "interval"):
        raise HTTPException(status_code=400, detail="mode must be 'daily' or 'interval'")
    try:
        _parse_time(body.time)
    except Exception:
        raise HTTPException(status_code=400, detail="time must be HH:MM (24h)")
    if not (1 <= int(body.interval_hours) <= 168):
        raise HTTPException(status_code=400, detail="interval_hours must be between 1 and 168")
    if not (0 <= int(body.keep_days) <= 3650):
        raise HTTPException(status_code=400, detail="keep_days must be between 0 and 3650")
    if not str(body.path or "").strip():
        raise HTTPException(status_code=400, detail="Backup folder is required")
    folder = _ensure_folder(body.path)

    override = (body.pg_dump_path or "").strip()
    if override:
        resolved = override if os.path.isfile(override) else shutil.which(override)
        if not resolved or not os.path.isfile(resolved):
            raise HTTPException(status_code=400, detail=f"pg_dump not found at: {override}")
        override = os.path.abspath(resolved)
        ver, _ = _dump_version(override)
        server_ver, _ = _server_version()
        if ver and server_ver and ver[0] < server_ver[0]:
            raise HTTPException(
                status_code=400,
                detail=f"pg_dump {ver[0]}.{ver[1]} is older than the database server "
                       f"{server_ver[0]}.{server_ver[1]} — pick a newer pg_dump",
            )
    else:
        override = None

    cfg = _load()
    cfg.update({
        "enabled": bool(body.enabled),
        "mode": body.mode,
        "time": body.time,
        "interval_hours": int(body.interval_hours),
        "keep_days": int(body.keep_days),
        "path": folder,
        "pg_dump_path": override,
    })
    # Forget the cached pick when the override changes.
    cfg["next_run"] = _compute_next_run(cfg) if cfg["enabled"] else None
    with _lock:
        _save(cfg)
    return _state()


@router.post("/backup/run")
def run_backup_now(current_user: User = Depends(get_current_active_admin)):
    """Start a backup in the background; poll GET /backup for the result."""
    if not _start_backup("manual"):
        raise HTTPException(status_code=409, detail="A backup is already running")
    return {"started": True}


@router.delete("/backup/file")
def delete_backup_file(name: str = Query(..., min_length=1),
                       current_user: User = Depends(get_current_active_admin)):
    """Delete one .bak file from the configured folder (path-safe)."""
    cfg = _load()
    safe = os.path.basename(name)
    if safe != name or not safe.lower().endswith(FILE_SUFFIX):
        raise HTTPException(status_code=400, detail="Invalid backup file name")
    target = os.path.join(cfg["path"], safe)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Backup file not found")
    try:
        os.remove(target)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not delete file: {e}")
    return {"deleted": True, "name": safe}
