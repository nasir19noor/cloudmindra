from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.audit import audit, event_out
from core.health import system_health
from core.jobs import job_out
from core.auth import client_ip, require_admin
from core.auth import SESSION_COOKIE, current_user
from core.database import get_db
from core.catalog import APPS, LABELS, LIMITS, WORKSPACE_SEATS
from core.entitlements import row_is_pro, seat_limit, utc_iso
from core import models as db_models
from website import models as site_models
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
    admin_email: str = Depends(require_admin),
):
    row = db.get(db_models.User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    me = current_user(request)
    # Removing your own admin access would lock you out mid-session
    if me and me["sub"] == user_id and not payload.is_admin:
        raise HTTPException(status_code=400, detail="You cannot remove your own admin access")
    if row.is_admin != payload.is_admin:
        audit(db, "platform.admin_granted" if payload.is_admin else "platform.admin_revoked", actor_id=me and me["sub"],
              actor_email=admin_email, target_id=user_id, metadata={"email": row.email}, ip=client_ip(request))
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
            "pro_until": utc_iso(r.pro_until),
            "overrides": r.limits or {},
        }
    return out


def _module_out(key: str, app: dict, state: dict | None) -> dict:
    """Tier plus what the overrides editor needs: each limit's Free and Pro default and its label."""
    state = state or {"tier": "free", "pro_until": None, "overrides": {}}
    return {
        "name": app["name"], **state,
        "limits": {k: {"free": LIMITS[key]["free"][k], "pro": LIMITS[key]["pro"][k], "label": LABELS.get(k, k),
                       "override": state["overrides"].get(k)} for k in LIMITS[key]["free"]},
    }


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
        "modules": {key: _module_out(key, app, tiers.get(key)) for key, app in APPS.items() if app["available"]},
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
async def update_workspace_seats(org_id: str, payload: SeatLimitUpdate, request: Request, db: Session = Depends(get_db),
                                 admin_email: str = Depends(require_admin)):
    org = db.get(db_models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if org.member_limit != payload.member_limit:
        audit(db, "org.seat_limit_changed", org_id=org_id, actor_email=admin_email, target_id=org_id,
              metadata={"from": org.member_limit, "to": payload.member_limit}, ip=client_ip(request))
    org.member_limit = payload.member_limit
    db.commit()
    members, pending, owners = _seat_counts(db)
    return _workspace_out(db, org, sorted(owners[org.id]), members.get(org.id, 0), pending.get(org.id, 0),
                          _module_tiers(db)[org.id])


@router.put("/orgs/{org_id}/modules/{app_key}")
async def set_module_tier(org_id: str, app_key: str, payload: ModuleTierUpdate, request: Request,
                          admin_email: str = Depends(require_admin), db: Session = Depends(get_db)):
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
    was = "pro" if row_is_pro(row) else "free"
    audit(db, "module.tier_changed", org_id=org_id, actor_email=admin_email, app_key=app_key, target_id=org_id,
          metadata={"from": was, "to": payload.tier, "pro_until": payload.pro_until.isoformat() if payload.pro_until else None,
                    "limits": payload.limits}, ip=client_ip(request))
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


@router.get("/activity")
async def platform_activity(limit: int = 200, org_id: str | None = None, db: Session = Depends(get_db),
                            _: str = Depends(require_admin)):
    """Audit log across all workspaces (DESIGN.md §7), newest first; filter with ?org_id=."""
    q = db.query(db_models.AuditEvent)
    if org_id:
        q = q.filter(db_models.AuditEvent.org_id == org_id)
    rows = q.order_by(db_models.AuditEvent.created_at.desc(), db_models.AuditEvent.id.desc()).limit(max(1, min(limit, 1000)))
    return [event_out(e) for e in rows]


# --- System health and jobs (DESIGN.md §7) ---------------------------------------------

@router.get("/system")
async def system(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    """Job queue, outbox backlog and module signals; status "warning" lists what needs attention."""
    return system_health(db)


@router.get("/jobs")
async def list_jobs(status: str | None = None, org_id: str | None = None, type: str | None = None, limit: int = 100,
                    db: Session = Depends(get_db), _: str = Depends(require_admin)):
    q = db.query(db_models.Job)
    if status:
        q = q.filter(db_models.Job.status == status)
    if org_id:
        q = q.filter(db_models.Job.org_id == org_id)
    if type:
        q = q.filter(db_models.Job.type == type)
    rows = q.order_by(db_models.Job.created_at.desc()).limit(max(1, min(limit, 500))).all()
    names = dict(db.query(db_models.Organization.id, db_models.Organization.name)
                 .filter(db_models.Organization.id.in_({j.org_id for j in rows if j.org_id})))
    return [{**job_out(j), "org_id": j.org_id, "org_name": names.get(j.org_id), "error_full": j.error,
             "payload": j.payload, "locked_by": j.locked_by} for j in rows]


def _job_or_404(db: Session, job_id: str) -> "db_models.Job":
    job = db.get(db_models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request, admin_email: str = Depends(require_admin), db: Session = Depends(get_db)):
    """Run a failed or cancelled job again from attempt 1."""
    job = _job_or_404(db, job_id)
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Only failed or cancelled jobs can be retried (this one is {job.status})")
    audit(db, "job.retried", org_id=job.org_id, actor_email=admin_email, target_id=job.id,
          metadata={"type": job.type, "was": job.status, "attempts": job.attempts}, ip=client_ip(request))
    job.status, job.attempts, job.run_at, job.finished_at = "queued", 0, datetime.now(timezone.utc), None
    job.locked_by = job.locked_at = None
    db.commit()
    return job_out(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request, admin_email: str = Depends(require_admin), db: Session = Depends(get_db)):
    """Stop a queued job (including one waiting for a retry) from running."""
    job = _job_or_404(db, job_id)
    if job.status != "queued":
        raise HTTPException(status_code=409, detail=f"Only queued jobs can be cancelled (this one is {job.status})")
    # Conditional update: a worker may claim the job between the check above and this write
    changed = (db.query(db_models.Job)
               .filter(db_models.Job.id == job_id, db_models.Job.status == "queued")
               .update({"status": "cancelled", "finished_at": datetime.now(timezone.utc)}, synchronize_session=False))
    if not changed:
        db.rollback()
        raise HTTPException(status_code=409, detail="The job started running before it could be cancelled")
    audit(db, "job.cancelled", org_id=job.org_id, actor_email=admin_email, target_id=job.id,
          metadata={"type": job.type, "attempts": job.attempts}, ip=client_ip(request))
    db.commit()
    db.refresh(job)
    return job_out(job)


@router.get("/me")
async def me(username: str = Depends(require_admin)):
    return {"username": username}


def _top(db: Session, column, since: datetime, limit: int = 10, *filters):
    q = (
        db.query(column, func.count(site_models.PageVisit.id).label("visits"))
        .filter(site_models.PageVisit.visited_at >= since, column.isnot(None), *filters)
        .group_by(column)
        .order_by(func.count(site_models.PageVisit.id).desc())
        .limit(limit)
    )
    return [{"label": label, "visits": visits} for label, visits in q.all()]


@router.get("/analytics")
async def analytics(days: int = 30, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    PV = site_models.PageVisit
    in_range = PV.visited_at >= since

    total_visits = db.query(func.count(PV.id)).filter(in_range).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(PV.visitor_ip))).filter(in_range).scalar() or 0
    contacts = (
        db.query(func.count(site_models.ContactSubmission.id))
        .filter(site_models.ContactSubmission.created_at >= since)
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
