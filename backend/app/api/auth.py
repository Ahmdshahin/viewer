from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.api import deps
from app.core.security import verify_password, create_access_token
from app.core.config import settings
from app.db.models import User
from pydantic import BaseModel
from typing import List

router = APIRouter()

class Token(BaseModel):
    access_token: str
    token_type: str

class UserResponse(BaseModel):
    username: str
    role: str
    is_active: bool = True
    full_name: str | None = None
    permissions: List[str] = []

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str | None = None
    username: str | None = None
    user: UserResponse

@router.post("/login", response_model=LoginResponse)
def login_access_token(db: Session = Depends(deps.get_db), form_data: OAuth2PasswordRequestForm = Depends()):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    elif not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    
    access_token_expires = timedelta(minutes=60 * 24)
    access_token = create_access_token(
        subject=str(user.id),
        role=user.role,
        expires_delta=access_token_expires,
        extra_claims={"username": user.username}
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "user": {"username": user.username, "role": user.role, "is_active": user.is_active, "full_name": user.full_name,
                 "permissions": deps.effective_pages(user)}
    }

@router.get("/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(deps.get_current_user)):
    return {"username": current_user.username, "role": current_user.role, "is_active": current_user.is_active, "full_name": current_user.full_name,
            "permissions": deps.effective_pages(current_user)}

