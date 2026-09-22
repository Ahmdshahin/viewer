"""Per-user map viewer preferences (layer color/opacity/visibility, order, labels, basemap).

Stored as a single JSONB row per user so each account keeps its own custom
view, layered on top of the admin-curated map_layers config.
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.db.models import User

router = APIRouter()

MAX_PAYLOAD = 20000


class PrefsIn(BaseModel):
    data: dict


def _ensure(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            username VARCHAR(100) PRIMARY KEY,
            data JSONB NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """))
    db.commit()


@router.get("")
def get_prefs(db: Session = Depends(deps.get_db),
              current_user: User = Depends(deps.get_current_user)):
    _ensure(db)
    row = db.execute(
        text("SELECT data FROM user_prefs WHERE username = :u"),
        {"u": current_user.username},
    ).mappings().first()
    data = (row["data"] if row and row["data"] else {}) or {}
    return {"data": data}


@router.put("")
def put_prefs(body: PrefsIn,
              db: Session = Depends(deps.get_db),
              current_user: User = Depends(deps.get_current_user)):
    payload = json.dumps(body.data)
    if len(payload) > MAX_PAYLOAD:
        raise HTTPException(status_code=422, detail="Preferences payload too large")
    _ensure(db)
    db.execute(text("""
        INSERT INTO user_prefs (username, data, updated_at)
        VALUES (:u, CAST(:d AS jsonb), now())
        ON CONFLICT (username) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
    """), {"u": current_user.username, "d": payload})
    db.commit()
    return {"ok": True}