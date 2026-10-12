"""Customer login through Amazon Cognito (managed login + Sign in with Google).

The backend runs the OAuth authorization-code flow with PKCE: it holds the client
secret, verifies the ID token, then issues its own signed session cookie.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from functools import lru_cache
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

SESSION_COOKIE = "cm_session"
STATE_COOKIE = "cm_oauth"
SESSION_TTL = 60 * 60 * 12  # 12 hours
STATE_TTL = 60 * 10  # time allowed to finish the login page

_REQUIRED = (
    "COGNITO_DOMAIN",
    "COGNITO_CLIENT_ID",
    "COGNITO_CLIENT_SECRET",
    "COGNITO_ISSUER",
    "COGNITO_REDIRECT_URI",
    "SESSION_SECRET",
)


def cognito_configured() -> bool:
    return all(os.getenv(name) for name in _REQUIRED)


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "https://cloudmindra.com").rstrip("/")


def _domain() -> str:
    return os.environ["COGNITO_DOMAIN"].rstrip("/")


# --- Signed cookies -------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: str) -> str:
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Login is not configured")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def encode_signed(data: dict, ttl: int) -> str:
    payload = _b64(json.dumps({**data, "exp": int(time.time()) + ttl}).encode())
    return f"{payload}.{_sign(payload)}"


def decode_signed(token: str | None) -> dict | None:
    """Return the payload of a valid, unexpired signed value, else None."""
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data


# --- OAuth flow -----------------------------------------------------------

def new_login_state() -> tuple[str, str]:
    """Return (state, PKCE verifier) for one login attempt."""
    return secrets.token_urlsafe(24), secrets.token_urlsafe(48)


def authorize_url(state: str, verifier: str, provider: str | None = None) -> str:
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    params = {
        "response_type": "code",
        "client_id": os.environ["COGNITO_CLIENT_ID"],
        "redirect_uri": os.environ["COGNITO_REDIRECT_URI"],
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    # Skip the managed login page and go straight to Google
    if provider:
        params["identity_provider"] = provider
    return f"{_domain()}/oauth2/authorize?{urlencode(params)}"


def logout_url() -> str:
    params = {"client_id": os.environ["COGNITO_CLIENT_ID"], "logout_uri": f"{frontend_url()}/"}
    return f"{_domain()}/logout?{urlencode(params)}"


def exchange_code(code: str, verifier: str) -> dict:
    client_id = os.environ["COGNITO_CLIENT_ID"]
    client_secret = os.environ["COGNITO_CLIENT_SECRET"]
    body = urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": os.environ["COGNITO_REDIRECT_URI"],
        "code_verifier": verifier,
    }).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        f"{_domain()}/oauth2/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=400, detail="Login code was rejected") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the login service") from exc


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{os.environ['COGNITO_ISSUER'].rstrip('/')}/.well-known/jwks.json")


def verify_id_token(id_token: str) -> dict:
    try:
        key = _jwks_client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=os.environ["COGNITO_CLIENT_ID"],
            issuer=os.environ["COGNITO_ISSUER"].rstrip("/"),
        )
    except jwt.PyJWTError as exc:
        logger.warning("ID token rejected: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=401, detail="Invalid ID token") from exc
    if claims.get("token_use") != "id":
        raise HTTPException(status_code=401, detail="Invalid ID token")
    return claims


def user_from_claims(claims: dict) -> dict:
    identities = claims.get("identities") or []
    provider = identities[0].get("providerName", "Cognito") if identities else "Cognito"
    return {
        "sub": claims["sub"],
        "email": claims.get("email", ""),
        "name": claims.get("name") or claims.get("email", ""),
        "provider": provider,
        "groups": claims.get("cognito:groups", []),
    }


# --- Dependencies ---------------------------------------------------------

def current_user(request: Request) -> dict | None:
    return decode_signed(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
