from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api import deps
from app.db.models import User
from app.core.security import hash_password
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    role: str = "editor"
    permissions: Optional[List[str]] = None

class UserUpdate(BaseModel):
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None
    password: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    role: str
    is_active: bool
    permissions: List[str] = []

    class Config:
        orm_mode = True

def _clean_pages(pages) -> Optional[list]:
    if pages is None:
        return None
    return [p for p in pages if p in deps.PAGE_KEYS]

def _out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "permissions": deps.effective_pages(user),
    }

@router.get("", response_model=List[UserOut])
def get_users(db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    users = db.query(User).all()
    return [_out(u) for u in users]

@router.post("", response_model=UserOut)
def create_user(user_in: UserCreate, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    user = db.query(User).filter(User.username == user_in.username).first()
    if user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    db_user = User(
        username=user_in.username,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        permissions=_clean_pages(user_in.permissions),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return _out(db_user)

@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, user_in: UserUpdate, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    """Admin-only: change a user's role and/or granted pages (never your own)."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role or pages.")
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if user_in.role is not None:
        if user_in.role not in ("admin", "editor", "viewer"):
            raise HTTPException(status_code=400, detail="Invalid role.")
        db_user.role = user_in.role
    if user_in.permissions is not None:
        db_user.permissions = _clean_pages(user_in.permissions)
    if user_in.is_active is not None:
        db_user.is_active = user_in.is_active
    if user_in.full_name is not None:
        db_user.full_name = user_in.full_name
    if user_in.password is not None:
        if not user_in.password.strip():
            raise HTTPException(status_code=400, detail="Password cannot be empty.")
        if len(user_in.password.strip()) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        db_user.hashed_password = hash_password(user_in.password)
    db.commit()
    db.refresh(db_user)
    return _out(db_user)


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(deps.get_db), current_user: User = Depends(deps.get_current_active_admin)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself.")
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    # A user can only be deleted when they are not linked to any saved data
    # (cadastral rows, migrated layers, or audit records).
    uname = db_user.username
    data_tables = ("lands", "eshghalat", "points", "mudryia", "regoin")
    linked = []
    for t in data_tables:
        try:
            n = db.execute(text(f'SELECT COUNT(*) FROM "{t}" WHERE "created_by" = :u'), {"u": uname}).scalar()
        except Exception:
            n = 0
        if n:
            linked.append(f"{t} ({n} rows)")
    try:
        audit_n = db.execute(
            text('SELECT COUNT(*) FROM audit_trail WHERE "user_id" = :uid OR "username" = :u'),
            {"uid": user_id, "u": uname},
        ).scalar()
    except Exception:
        audit_n = 0
    if audit_n:
        linked.append(f"audit_trail ({audit_n} records)")

    if linked:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete @{uname}: user is linked to data — {', '.join(linked)}.",
        )

    db.delete(db_user)
    db.commit()
    return {"status": "deleted"}
