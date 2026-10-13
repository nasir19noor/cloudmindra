import asyncio
import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from monitoring import (
    INTERVALS,
    allowed_intervals,
    SSL_WARN_DAYS,
    UnsafeURL,
    assert_public_host,
    aware,
    normalize_url,
    run_check,
    utcnow,
)
from entitlements import limits as module_limits, require_below, tier, upgrade_hint
from orgs import OrgContext, org_access, org_query
import db_models

router = APIRouter(prefix="/api/orgs/{org_id}/uptime/monitors", tags=["uptime"])

READ = org_access("uptime.read")
WRITE = org_access("uptime.write")

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


def _owned(db: Session, monitor_id: str, ctx: OrgContext) -> db_models.Monitor:
    m = org_query(db, db_models.Monitor, ctx).filter(db_models.Monitor.id == monitor_id).first()
    # Same 404 for "missing" and "another workspace's" so ids cannot be probed
    if m is None:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return m


def _check_interval(db: Session, ctx: OrgContext, minutes: int) -> None:
    if minutes not in INTERVALS:
        raise HTTPException(status_code=422, detail=f"Interval must be one of {', '.join(map(str, INTERVALS))} minutes")
    minimum = module_limits(db, ctx.org_id, "uptime")["uptime.min_interval"]
    if minutes < minimum:
        raise HTTPException(status_code=402, detail=f"Checks every {minutes} minute{'s' if minutes > 1 else ''} need "
                                                    f"Uptime Pro (this workspace's minimum is {minimum}). {upgrade_hint('uptime')}")


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
def list_monitors(ctx: OrgContext = Depends(READ), db: Session = Depends(get_db)):
    monitors = org_query(db, db_models.Monitor, ctx).order_by(db_models.Monitor.created_at).all()
    lim = module_limits(db, ctx.org_id, "uptime")
    return {
        "monitors": _serialize(db, monitors),
        "tier": tier(db, ctx.org_id, "uptime"),
        "limit": lim["uptime.monitors"],
        "intervals": allowed_intervals(lim["uptime.min_interval"]),
        "locked_intervals": [i for i in INTERVALS if i < lim["uptime.min_interval"]],
        "history_days": lim["uptime.history_days"],
    }


@router.post("", status_code=201)
async def create_monitor(payload: MonitorCreate, ctx: OrgContext = Depends(WRITE), db: Session = Depends(get_db)):
    _check_interval(db, ctx, payload.interval_minutes)
    require_below(db, ctx.org_id, "uptime.monitors", org_query(db, db_models.Monitor, ctx).count())
    try:
        url = normalize_url(payload.url)
        await asyncio.to_thread(assert_public_host, url)
    except UnsafeURL as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    m = db_models.Monitor(id=str(uuid.uuid4()), org_id=ctx.org_id, created_by=ctx.user_id,
                          name=payload.name.strip(), url=url, interval_minutes=payload.interval_minutes)
    db.add(m)
    db.commit()

    # First result straight away so the customer sees it working
    await run_check(m.id, m.url, ssl_due=m.url.startswith("https://"))
    db.expire_all()
    return _serialize(db, [db.get(db_models.Monitor, m.id)])[0]


@router.patch("/{monitor_id}")
def update_monitor(monitor_id: str, payload: MonitorUpdate, ctx: OrgContext = Depends(WRITE),
                   db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, ctx)
    if payload.name is not None:
        m.name = payload.name.strip()
    if payload.interval_minutes is not None:
        _check_interval(db, ctx, payload.interval_minutes)
        m.interval_minutes = payload.interval_minutes
    if payload.is_active is not None and payload.is_active != m.is_active:
        m.is_active = payload.is_active
        # Resume from a clean slate rather than alerting on stale failures
        m.consecutive_failures = 0
    db.commit()
    return _serialize(db, [m])[0]


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: str, ctx: OrgContext = Depends(WRITE), db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, ctx)
    db.query(db_models.MonitorCheck).filter(db_models.MonitorCheck.monitor_id == m.id).delete()
    db.delete(m)
    db.commit()


@router.post("/{monitor_id}/check")
async def check_now(monitor_id: str, ctx: OrgContext = Depends(WRITE), db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, ctx)
    if m.last_checked_at and utcnow() - aware(m.last_checked_at) < CHECK_NOW_COOLDOWN:
        raise HTTPException(status_code=429, detail="Checked a moment ago. Try again in a few seconds.")
    await run_check(m.id, m.url, ssl_due=False)
    db.expire_all()
    return _serialize(db, [db.get(db_models.Monitor, m.id)])[0]


@router.get("/{monitor_id}/checks")
def monitor_checks(monitor_id: str, hours: int = 24, ctx: OrgContext = Depends(READ),
                   db: Session = Depends(get_db)):
    m = _owned(db, monitor_id, ctx)
    hours = max(1, min(hours, 24 * module_limits(db, ctx.org_id, "uptime")["uptime.history_days"]))
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
