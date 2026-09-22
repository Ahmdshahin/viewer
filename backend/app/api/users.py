from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
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
    db.delete(db_user)
    db.commit()
    return {"status": "deleted"}
