"""In-memory named selections (request-number sets).

Lets tile/stats/rows/export endpoints share one selection created by the
attribute/location search, without stuffing thousands of ids into URLs.
Entries expire after 30 minutes; clients delete them explicitly on clear.
"""

import time
import uuid

_TTL_SECONDS = 30 * 60
_MAX_REQS = 100000
_STORE = {}  # sel_id -> {"reqs": [...], "created": timestamp}


def purge_expired() -> None:
    now = time.time()
    for key in [k for k, v in _STORE.items() if now - v["created"] > _TTL_SECONDS]:
        _STORE.pop(key, None)


def create_selection(reqs) -> str:
    purge_expired()
    sid = uuid.uuid4().hex[:12]
    _STORE[sid] = {
        "reqs": [r for r in (reqs or []) if r][: _MAX_REQS],
        "created": time.time(),
    }
    return sid


def get_selection(sid) -> list | None:
    """Request list, [] when empty, None when unknown/expired."""
    purge_expired()
    entry = _STORE.get(sid)
    return entry["reqs"] if entry is not None else None


def delete_selection(sid) -> None:
    _STORE.pop(sid, None)
