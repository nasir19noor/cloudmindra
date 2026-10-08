import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "cm_admin"
SESSION_TTL = 60 * 60 * 12  # 12 hours


def _secret() -> bytes:
    secret = os.getenv("ADMIN_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Admin is not configured")
    return secret.encode()


def admin_configured() -> bool:
    return bool(os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD") and os.getenv("ADMIN_SECRET"))


def verify_credentials(username: str, password: str) -> bool:
    expected_user = os.getenv("ADMIN_USERNAME", "")
    expected_pass = os.getenv("ADMIN_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    user_ok = hmac.compare_digest(username.encode(), expected_user.encode())
    pass_ok = hmac.compare_digest(password.encode(), expected_pass.encode())
    return user_ok and pass_ok


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token(username: str) -> str:
    payload = f"{username}|{int(time.time()) + SESSION_TTL}"
    return f"{payload}|{_sign(payload)}"


def verify_session_token(token: str | None) -> str | None:
    """Return the username for a valid, unexpired token, else None."""
    if not token:
        return None
    try:
        username, exp, sig = token.rsplit("|", 2)
        expires = int(exp)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(f"{username}|{exp}")):
        return None
    if expires < time.time():
        return None
    # Invalidate sessions if the admin username changes in .env
    if username != os.getenv("ADMIN_USERNAME"):
        return None
    return username


def require_admin(request: Request) -> str:
    username = verify_session_token(request.cookies.get(COOKIE_NAME))
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username


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
