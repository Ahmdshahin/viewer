"""Per-user notification endpoints (bell badge, list, mark-read)."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.api import deps
from app.db.models import Notification, User

router = APIRouter()


class ReadIn(BaseModel):
    id: Optional[int] = None
    all: bool = False


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "link_req": n.link_req,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("")
def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)  # noqa: E712
    items = q.order_by(Notification.id.desc()).limit(limit).all()
    return {"items": [_out(n) for n in items]}


@router.get("/count")
def notification_count(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    unread = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,  # noqa: E712
    ).scalar() or 0
    return {"unread": unread}


@router.post("/read")
def mark_read(
    body: ReadIn,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if body.id is not None:
        q = q.filter(Notification.id == body.id)
    elif not body.all:
        raise HTTPException(status_code=400, detail="Provide id or all=true")
    n = q.update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"updated": n}