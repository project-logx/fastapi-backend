from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.auth import decode_access_token


# ─── Database session dependency ─────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── JWT bearer scheme ────────────────────────────────────────────────────────
# auto_error=False so we can return a cleaner 401 ourselves instead of 403.

_bearer = HTTPBearer(auto_error=False)


# ─── Current user dependency ──────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    FastAPI dependency that validates the Bearer JWT sent in the
    Authorization header and returns the authenticated User ORM object.

    Usage in a route:
        @router.get("/me")
        def me(current_user = Depends(get_current_user)):
            return {"id": current_user.id, "email": current_user.email}

    Raises HTTP 401 if:
      - No Authorization header is present
      - Token is malformed, has a bad signature, or is expired
      - The user_id in the token does not exist in the database
    """
    from app.models import User  # local import to avoid circular deps

    _unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. Must have an Authorization: Bearer <token> header
    if credentials is None or not credentials.credentials:
        raise _unauthorized

    token = credentials.credentials

    # 2. Verify signature + expiry using the existing service function
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # 3. Extract user id from the 'sub' claim
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise _unauthorized

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise _unauthorized

    # 4. Look up the user in the database
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _unauthorized

    return user
