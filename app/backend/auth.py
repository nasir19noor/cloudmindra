import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from cognito_auth import current_user
from database import get_db
import db_models


def require_admin(request: Request, db: Session = Depends(get_db)) -> str:
    """Allow a signed-in user whose account is flagged as admin."""
    # Checked against the database on every request so revoking admin applies immediately
    user = current_user(request)
    if user:
        row = db.get(db_models.User, user["sub"])
        if row and row.is_admin:
            return row.email
    raise HTTPException(status_code=401, detail="Not authenticated")


def cookie_secure() -> bool:
    # Allow plain-http cookies for local development only
    return os.getenv("ADMIN_COOKIE_SECURE", "true").strip().lower() not in ("0", "false", "no")


def client_ip(request: Request) -> str:
    # nginx sets X-Real-IP to the connecting address; prefer it over the spoofable X-Forwarded-For
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
