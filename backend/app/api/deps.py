from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, get_engine
from app.core.config import settings
from app.core.security import decode_access_token
from app.db.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

# Pages the admin can grant per user (avatar menu / routes).
PAGE_KEYS = ("processor", "dashboard", "users", "database")
ROLE_DEFAULT_PAGES = {
    "admin": ["processor", "dashboard", "users", "database"],
    "editor": ["processor", "dashboard"],
    "viewer": ["dashboard"],
}


def effective_pages(user) -> list:
    """Pages a user may open: explicit admin grant, else the role default."""
    stored = getattr(user, "permissions", None)
    if isinstance(stored, list) and stored:
        return [p for p in stored if p in PAGE_KEYS]
    return list(ROLE_DEFAULT_PAGES.get(getattr(user, "role", "viewer"), ROLE_DEFAULT_PAGES["viewer"]))

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal(bind=get_engine())
    try:
        yield db
    finally:
        db.close()

def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    token_data = decode_access_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.username == token_data.get("username")).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user

def get_current_active_editor(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ["admin", "editor"]:
        raise HTTPException(status_code=403, detail="The user doesn't have enough privileges")
    return current_user

def get_current_active_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="The user doesn't have enough privileges")
    return current_user
