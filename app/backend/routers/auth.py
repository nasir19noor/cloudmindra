from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth import cookie_secure
from cognito_auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    STATE_COOKIE,
    STATE_TTL,
    authorize_url,
    cognito_configured,
    decode_signed,
    encode_signed,
    exchange_code,
    frontend_url,
    logout_url,
    new_login_state,
    require_user,
    seed_admin_emails,
    user_from_claims,
    verify_id_token,
)
from database import get_db
import db_models

router = APIRouter(prefix="/api/auth", tags=["auth"])

PROVIDERS = {"google": "Google"}

# Frontend pages a login may return to; anything else falls back to the portal
NEXT_PAGES = ("/portal", "/admin")


def _portal_redirect(error: str | None = None, next_page: str = "/portal") -> RedirectResponse:
    page = next_page if next_page in NEXT_PAGES else "/portal"
    query = f"?{urlencode({'error': error})}" if error else ""
    return RedirectResponse(f"{frontend_url()}{page}{query}", status_code=303)


@router.get("/login")
def login(provider: Literal["google"] | None = None, next: str = "/portal"):
    if not cognito_configured():
        raise HTTPException(status_code=503, detail="Login is not configured")

    state, verifier = new_login_state()
    next_page = next if next in NEXT_PAGES else "/portal"
    response = RedirectResponse(authorize_url(state, verifier, PROVIDERS.get(provider)), status_code=303)
    # Lax still sends this cookie on the top-level redirect back from Cognito
    response.set_cookie(
        STATE_COOKIE,
        encode_signed({"state": state, "verifier": verifier, "next": next_page}, STATE_TTL),
        max_age=STATE_TTL,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/api/auth",
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    saved = decode_signed(request.cookies.get(STATE_COOKIE))
    next_page = saved.get("next", "/portal") if saved else "/portal"

    if error:
        return _portal_redirect("cancelled" if error == "access_denied" else "failed", next_page)

    if not code or not state or not saved or saved.get("state") != state:
        return _portal_redirect("expired", next_page)

    tokens = exchange_code(code, saved["verifier"])
    user = user_from_claims(verify_id_token(tokens["id_token"]))

    now = datetime.now(timezone.utc)
    row = db.get(db_models.User, user["sub"])
    if row is None:
        row = db_models.User(id=user["sub"], created_at=now)
        db.add(row)
    row.email = user["email"]
    row.name = user["name"]
    row.provider = user["provider"]
    row.last_login_at = now
    # Only a verified address can claim the seeded admin email
    if user["email_verified"] and user["email"].lower() in seed_admin_emails():
        row.is_admin = True
    db.commit()

    response = _portal_redirect(next_page=next_page)
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    response.set_cookie(
        SESSION_COOKIE,
        encode_signed({k: v for k, v in user.items() if k != "email_verified"}, SESSION_TTL),
        max_age=SESSION_TTL,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/logout")
def logout():
    # Also end the Cognito session, otherwise the next login skips the sign-in page
    target = logout_url() if cognito_configured() else f"{frontend_url()}/"
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(db_models.User, user["sub"])
    return {
        **{k: user[k] for k in ("sub", "email", "name", "provider", "groups")},
        "is_admin": bool(row and row.is_admin),
    }
