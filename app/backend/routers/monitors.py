import asyncio
import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cognito_auth import require_user
from database import get_db
from monitoring import (
    INTERVALS,
    SSL_WARN_DAYS,
    UnsafeURL,
    assert_public_host,
    aware,
    max_monitors_per_user,
    normalize_url,
    run_check,
    utcnow,
)
import db_models

router = APIRouter(prefix="/api/monitors", tags=["monitors"])

RECENT_CHECKS = 30  # bars shown per monitor in the portal
CHECK_NOW_COOLDOWN = timedelta(seconds=20)


class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=2048)
    interval_minutes: int = 5


class MonitorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    interval_minutes: int | None = None
    is_active: bool | None = None


def _iso(dt):
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _owned(db: Session, monitor_id: str, user: dict) -> db_models.Monitor:
    m = db.get(db_models.Monitor, monitor_id)
    # Same 404 for "missing" and "someone else's" so ids cannot be probed
    if m is None or m.user_id != user["sub"]:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return m


def _check_interval(minutes: int) -> None:
    if minutes not in INTERVALS:
        raise HTTPException(status_code=422, detail=f"Interval must be one of {', '.join(map(str, INTERVALS))} minutes")


def _serialize(db: Session, monitors: list[db_models.Monitor]) -> list[dict]:
    if not monitors:
        return []
    since = utcnow() - timedelta(hours=24)
    rows = (
        db.query(db_models.MonitorCheck)
        .filter(db_models.MonitorCheck.monitor_id.in_([m.id for m in monitors]),
                db_models.MonitorCheck.checked_at >= since)
        .order_by(db_models.MonitorCheck.checked_at)
        .all()
    )
    checks = defaultdict(list)
    for c in rows:
        checks[c.monitor_id].append(c)

    now = utcnow()
    out = []
    for m in monitors:
        day = checks[m.id]
        ssl_days = (aware(m.ssl_expires_at) - now).days if m.ssl_expires_at else None
        out.append({
            "id": m.id,
            "name": m.name,
            "url": m.url,
            "interval_minutes": m.interval_minutes,
            "is_active": m.is_active,
            "status": m.status if m.is_active else "paused",
            "last_checked_at": _iso(m.last_checked_at),
            "last_status_code": m.last_status_code,
            "last_response_ms": m.last_response_ms,
            "last_error": m.last_error,
            "down_since": _iso(m.down_since),
            "ssl_expires_at": _iso(m.ssl_expires_at),
            "ssl_days_left": ssl_days,
            "ssl_warning": ssl_days is not None and ssl_days <= SSL_WARN_DAYS,
            "uptime_24h": round(100 * sum(c.ok for c in day) / len(day), 2) if day else None,
            "recent": [
                {"at": _iso(c.checked_at), "ok": c.ok, "ms": c.response_ms, "error": c.error}
                for c in day[-RECENT_CHECKS:]
            ],
            "created_at": _iso(m.created_at),
        })
    return out


@router.get("")
def list_monitors(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    monitors = (
        db.query(db_models.Monitor)
        .filter(db_models.Monitor.user_id == user["sub"])
        .order_by(db_models.Monitor.created_at)
        .all()
    )
    return {"monitors": _serialize(db, monitors), "limit": max_monitors_per_user(), "intervals": INTERVALS}


@router.post("", status_code=201)
async def create_monitor(payload: MonitorCreate, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    _check_interval(payload.interval_minutes)
    if db.get(db_models.User, user["sub"]) is None:
        raise HTTPException(status_code=401, detail="Please sign in again")
    count = db.query(db_models.Monitor).filter(db_models.Monitor.user_id == user["sub"]).count()
    if count >= max_monitors_per_user():
        raise HTTPException(status_code=403, detail=f"You can monitor up to {max_monitors_per_user()} URLs")
    try:
        url = normalize_url(payload.url)
        await asyncio.to_thread(assert_public_host, url)
    except UnsafeURL as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    m = db_models.Monitor(id=str(uuid.uuid4()), user_id=user["sub"], name=payload.name.strip(), url=url,
                          interval_minutes=payload.interval_minutes)
    db.add(m)
    db.commit()

    # First result straight away so the customer sees it working
    await run_check(m.id, m.url, ssl_due=m.url.startswith("https://"))
    db.expire_all()
    return _serialize(db, [db.get(db_models.Monitor, m.id)])[0]


@router.patch("/{monitor_id}")
def update_monitor(monitor_id: str, payload: MonitorUpdate, user: dict = Depends(require_user),
                   db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, user)
    if payload.name is not None:
        m.name = payload.name.strip()
    if payload.interval_minutes is not None:
        _check_interval(payload.interval_minutes)
        m.interval_minutes = payload.interval_minutes
    if payload.is_active is not None and payload.is_active != m.is_active:
        m.is_active = payload.is_active
        # Resume from a clean slate rather than alerting on stale failures
        m.consecutive_failures = 0
    db.commit()
    return _serialize(db, [m])[0]


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: str, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, user)
    db.query(db_models.MonitorCheck).filter(db_models.MonitorCheck.monitor_id == m.id).delete()
    db.delete(m)
    db.commit()


@router.post("/{monitor_id}/check")
async def check_now(monitor_id: str, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, user)
    if m.last_checked_at and utcnow() - aware(m.last_checked_at) < CHECK_NOW_COOLDOWN:
        raise HTTPException(status_code=429, detail="Checked a moment ago. Try again in a few seconds.")
    await run_check(m.id, m.url, ssl_due=False)
    db.expire_all()
    return _serialize(db, [db.get(db_models.Monitor, m.id)])[0]


@router.get("/{monitor_id}/checks")
def monitor_checks(monitor_id: str, hours: int = 24, user: dict = Depends(require_user),
                   db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, user)
    hours = max(1, min(hours, 24 * 30))
    rows = (
        db.query(db_models.MonitorCheck)
        .filter(db_models.MonitorCheck.monitor_id == m.id,
                db_models.MonitorCheck.checked_at >= utcnow() - timedelta(hours=hours))
        .order_by(db_models.MonitorCheck.checked_at.desc())
        .limit(2000)
        .all()
    )
    return [
        {"at": _iso(c.checked_at), "ok": c.ok, "status_code": c.status_code, "ms": c.response_ms, "error": c.error}
        for c in rows
    ]
