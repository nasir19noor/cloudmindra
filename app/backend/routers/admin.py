import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import (
    COOKIE_NAME,
    SESSION_TTL,
    admin_configured,
    client_ip,
    cookie_secure,
    create_session_token,
    require_admin,
    verify_credentials,
)
from database import get_db
import db_models

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Simple in-memory brute-force guard: max 5 failed logins per IP per 15 minutes
_FAILED: dict[str, list[float]] = defaultdict(list)
_MAX_FAILS = 5
_WINDOW = 15 * 60


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    if not admin_configured():
        raise HTTPException(status_code=503, detail="Admin is not configured")

    ip = client_ip(request)
    now = time.time()
    _FAILED[ip] = [t for t in _FAILED[ip] if now - t < _WINDOW]
    if len(_FAILED[ip]) >= _MAX_FAILS:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    if not verify_credentials(payload.username, payload.password):
        _FAILED[ip].append(now)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    _FAILED.pop(ip, None)
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(payload.username),
        max_age=SESSION_TTL,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )
    return {"username": payload.username}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(username: str = Depends(require_admin)):
    return {"username": username}


def _top(db: Session, column, since: datetime, limit: int = 10, *filters):
    q = (
        db.query(column, func.count(db_models.PageVisit.id).label("visits"))
        .filter(db_models.PageVisit.visited_at >= since, column.isnot(None), *filters)
        .group_by(column)
        .order_by(func.count(db_models.PageVisit.id).desc())
        .limit(limit)
    )
    return [{"label": label, "visits": visits} for label, visits in q.all()]


@router.get("/analytics")
async def analytics(days: int = 30, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    PV = db_models.PageVisit
    in_range = PV.visited_at >= since

    total_visits = db.query(func.count(PV.id)).filter(in_range).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(PV.visitor_ip))).filter(in_range).scalar() or 0
    contacts = (
        db.query(func.count(db_models.ContactSubmission.id))
        .filter(db_models.ContactSubmission.created_at >= since)
        .scalar()
        or 0
    )

    # Daily series, zero-filled so the chart has a bar for every day
    day_col = func.date(PV.visited_at)
    rows = (
        db.query(day_col, func.count(PV.id), func.count(func.distinct(PV.visitor_ip)))
        .filter(in_range)
        .group_by(day_col)
        .all()
    )
    by_day = {str(d): (v, u) for d, v, u in rows}
    daily = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        v, u = by_day.get(d, (0, 0))
        daily.append({"date": d, "visits": v, "visitors": u})

    # Referrers grouped by host
    ref_counts: dict[str, int] = defaultdict(int)
    for (ref,) in db.query(PV.referrer).filter(in_range).all():
        host = urlparse(ref).netloc if ref else ""
        ref_counts[host.removeprefix("www.") or "Direct"] += 1
    referrers = [
        {"label": k, "visits": v} for k, v in sorted(ref_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    recent = db.query(PV).filter(in_range).order_by(PV.visited_at.desc()).limit(100).all()

    return {
        "days": days,
        "totals": {
            "visits": total_visits,
            "visitors": unique_visitors,
            "contacts": contacts,
            "pages_per_visitor": round(total_visits / unique_visitors, 2) if unique_visitors else 0,
        },
        "daily": daily,
        "pages": _top(db, PV.path, since),
        "referrers": referrers,
        "countries": _top(db, PV.country, since),
        "cities": _top(db, PV.city, since),
        "devices": _top(db, PV.device_type, since),
        "browsers": _top(db, PV.browser, since),
        "os": _top(db, PV.os, since),
        "recent": [
            {
                "visited_at": r.visited_at.isoformat() if r.visited_at else None,
                "path": r.path,
                "country": r.country,
                "city": r.city,
                "device": r.device_type,
                "browser": r.browser,
                "os": r.os,
                "referrer": r.referrer,
                "ip": r.visitor_ip,
            }
            for r in recent
        ],
    }
