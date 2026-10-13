from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import require_admin
from cognito_auth import SESSION_COOKIE, current_user
from database import get_db
from catalog import APPS, LIMITS, WORKSPACE_SEATS
from entitlements import row_is_pro, seat_limit
import db_models

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


class AdminUpdate(BaseModel):
    is_admin: bool


def _user_out(u: db_models.User, me_sub: str | None) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "provider": u.provider,
        "is_admin": u.is_admin,
        "is_self": u.id == me_sub,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
async def list_users(request: Request, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    me = current_user(request)
    rows = (
        db.query(db_models.User)
        .order_by(db_models.User.is_admin.desc(), db_models.User.last_login_at.desc().nullslast())
        .all()
    )
    return [_user_out(u, me and me["sub"]) for u in rows]


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: AdminUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    row = db.get(db_models.User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    me = current_user(request)
    # Removing your own admin access would lock you out mid-session
    if me and me["sub"] == user_id and not payload.is_admin:
        raise HTTPException(status_code=400, detail="You cannot remove your own admin access")
    row.is_admin = payload.is_admin
    db.commit()
    return _user_out(row, me and me["sub"])


class SeatLimitUpdate(BaseModel):
    # None removes the override and falls back to the tier default (3 Free / 10 with any Pro)
    member_limit: int | None = Field(None, ge=1, le=1000)


class ModuleTierUpdate(BaseModel):
    tier: Literal["free", "pro"]
    pro_until: datetime | None = None  # None = no end date
    # Per-workspace limit overrides for this module, e.g. {"uptime.monitors": 200}; {} clears them
    limits: dict[str, int] | None = None


def _module_tiers(db: Session) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in db.query(db_models.OrgApp):
        out[r.org_id][r.app_key] = {
            "tier": "pro" if row_is_pro(r) else "free",
            "pro_until": r.pro_until.isoformat() if r.pro_until else None,
            "overrides": r.limits or {},
        }
    return out


def _workspace_out(db: Session, org: db_models.Organization, owners: list[str], members: int, pending: int,
                   tiers: dict[str, dict] | None = None) -> dict:
    tiers = tiers or {}
    return {
        "id": org.id,
        "name": org.name,
        "owners": owners,
        "members": members,
        "pending_invites": pending,
        "member_limit": org.member_limit,
        "effective_limit": seat_limit(db, org),
        "default_limit": WORKSPACE_SEATS["pro" if any(t["tier"] == "pro" for t in tiers.values()) else "free"],
        "modules": {key: {"name": app["name"], **tiers.get(key, {"tier": "free", "pro_until": None, "overrides": {}})}
                    for key, app in APPS.items() if app["available"]},
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


def _seat_counts(db: Session):
    members = dict(
        db.query(db_models.Membership.org_id, func.count(db_models.Membership.id))
        .group_by(db_models.Membership.org_id).all()
    )
    pending = dict(
        db.query(db_models.Invitation.org_id, func.count(db_models.Invitation.id))
        .filter(db_models.Invitation.accepted_at.is_(None),
                db_models.Invitation.expires_at > datetime.now(timezone.utc))
        .group_by(db_models.Invitation.org_id).all()
    )
    owners = defaultdict(list)
    for org_id, email in (
        db.query(db_models.Membership.org_id, db_models.User.email)
        .join(db_models.User, db_models.User.id == db_models.Membership.user_id)
        .filter(db_models.Membership.role == "owner")
    ):
        owners[org_id].append(email)
    return members, pending, owners


@router.get("/orgs")
async def list_workspaces(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    members, pending, owners = _seat_counts(db)
    tiers = _module_tiers(db)
    orgs = db.query(db_models.Organization).order_by(db_models.Organization.created_at.desc()).all()
    return [_workspace_out(db, o, sorted(owners[o.id]), members.get(o.id, 0), pending.get(o.id, 0), tiers[o.id])
            for o in orgs]


@router.put("/orgs/{org_id}")
async def update_workspace_seats(org_id: str, payload: SeatLimitUpdate, db: Session = Depends(get_db),
                                 _: str = Depends(require_admin)):
    org = db.get(db_models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    org.member_limit = payload.member_limit
    db.commit()
    members, pending, owners = _seat_counts(db)
    return _workspace_out(db, org, sorted(owners[org.id]), members.get(org.id, 0), pending.get(org.id, 0),
                          _module_tiers(db)[org.id])


@router.put("/orgs/{org_id}/modules/{app_key}")
async def set_module_tier(org_id: str, app_key: str, payload: ModuleTierUpdate, admin_email: str = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Switch a module between Free and Pro for one workspace (Pro is set by hand until billing exists)."""
    org = db.get(db_models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if app_key not in APPS:
        raise HTTPException(status_code=404, detail="Unknown module")
    known = LIMITS[app_key]["free"].keys()
    if payload.limits and (bad := sorted(set(payload.limits) - set(known))):
        raise HTTPException(status_code=422, detail=f"Unknown limits for {app_key}: {', '.join(bad)}")
    if payload.limits and any(v < 0 for v in payload.limits.values()):
        raise HTTPException(status_code=422, detail="Limits cannot be negative")

    row = db.get(db_models.OrgApp, (org_id, app_key))
    if row is None:
        row = db_models.OrgApp(org_id=org_id, app_key=app_key)
        db.add(row)
    if payload.tier == "pro" and not row_is_pro(row):
        row.pro_since = datetime.now(timezone.utc)
    row.tier = payload.tier
    row.status = "active"
    row.pro_until = payload.pro_until if payload.tier == "pro" else None
    if payload.limits is not None:
        row.limits = payload.limits or None
    row.updated_by = admin_email
    db.commit()
    members, pending, owners = _seat_counts(db)
    return _workspace_out(db, org, sorted(owners[org.id]), members.get(org.id, 0), pending.get(org.id, 0),
                          _module_tiers(db)[org.id])


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
