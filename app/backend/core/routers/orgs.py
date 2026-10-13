import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import require_user
from core.database import get_db
from core.entitlements import free_workspace_limit, modules_overview, owned_free_workspace_count
from core.audit import audit, audit_ctx, event_out
from core.catalog import APPS, NOTIFICATION_EVENTS
from core.auth import client_ip
from core.jobs import job_out
from core.orgs import OrgContext, create_workspace, delete_workspace, org_access
from core import models as db_models
router = APIRouter(prefix="/api/orgs", tags=["workspaces"])

CURRENCY = re.compile(r"^[A-Z]{3}$")


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    currency: str | None = None


def _iso(dt):
    return dt.isoformat() if dt else None


def _workspace_out(org: db_models.Organization, role: str, member_count: int | None = None) -> dict:
    out = {"id": org.id, "name": org.name, "currency": org.currency, "role": role, "created_at": _iso(org.created_at)}
    if member_count is not None:
        out["member_count"] = member_count
    return out


def _current_user(db: Session, user: dict) -> db_models.User:
    row = db.get(db_models.User, user["sub"])
    if row is None:
        raise HTTPException(status_code=401, detail="Please sign in again")
    return row


@router.get("")
def list_workspaces(user: dict = Depends(require_user), db: Session = Depends(get_db)):
    me = _current_user(db, user)
    rows = (
        db.query(db_models.Organization, db_models.Membership.role)
        .join(db_models.Membership, db_models.Membership.org_id == db_models.Organization.id)
        .filter(db_models.Membership.user_id == me.id)
        .order_by(db_models.Organization.created_at)
        .all()
    )
    return {
        "workspaces": [_workspace_out(org, role) for org, role in rows],
        "last_org_id": me.last_org_id,
        "free_workspace_limit": free_workspace_limit(),
    }


@router.post("", status_code=201)
def create(payload: WorkspaceCreate, request: Request, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    me = _current_user(db, user)
    # Only workspaces with no Pro module count (DESIGN.md §4.1)
    limit = free_workspace_limit()
    if owned_free_workspace_count(db, me.id) >= limit:
        raise HTTPException(status_code=403, detail=f"You can own up to {limit} workspaces without a Pro module. "
                                                    "Upgrade one of them, or contact CloudMindra.")
    org = create_workspace(db, me.id, payload.name)
    me.last_org_id = org.id
    audit(db, "org.created", org_id=org.id, actor_id=me.id, actor_email=me.email, target_id=org.id,
          metadata={"name": org.name}, ip=client_ip(request))
    db.commit()
    return _workspace_out(org, "owner", member_count=1)


@router.get("/{org_id}")
def get_workspace(ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    org = db.get(db_models.Organization, ctx.org_id)
    members = db.query(db_models.Membership).filter(db_models.Membership.org_id == ctx.org_id).count()
    return {**_workspace_out(org, ctx.role, member_count=members), "modules": modules_overview(db, ctx.org_id)}


@router.get("/{org_id}/modules")
def workspace_modules(ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """Each module's tier, limits, usage and features for this workspace (drives the portal)."""
    return modules_overview(db, ctx.org_id)


@router.patch("/{org_id}")
def update_workspace(payload: WorkspaceUpdate, ctx: OrgContext = Depends(org_access("org.update")),
                     db: Session = Depends(get_db)):
    org = db.get(db_models.Organization, ctx.org_id)
    changes = {}
    if payload.name is not None and payload.name.strip() != org.name:
        changes["name"] = [org.name, payload.name.strip()]
        org.name = payload.name.strip()
    if payload.currency is not None:
        currency = payload.currency.strip().upper()
        if not CURRENCY.match(currency):
            raise HTTPException(status_code=422, detail="Currency must be a 3-letter ISO code, e.g. USD or IDR")
        if currency != org.currency:
            changes["currency"] = [org.currency, currency]
        org.currency = currency
    if changes:
        audit_ctx(db, ctx, "org.updated", target_id=org.id, metadata=changes)
    db.commit()
    return _workspace_out(org, ctx.role)


@router.delete("/{org_id}", status_code=204)
def remove_workspace(ctx: OrgContext = Depends(org_access("org.delete")), db: Session = Depends(get_db)):
    mine = db.query(db_models.Membership).filter(db_models.Membership.user_id == ctx.user_id).count()
    if mine <= 1:
        raise HTTPException(status_code=400, detail="You cannot delete your only workspace")
    org = db.get(db_models.Organization, ctx.org_id)
    audit_ctx(db, ctx, "org.deleted", target_id=ctx.org_id, metadata={"name": org.name})
    delete_workspace(db, ctx.org_id)
    db.commit()


@router.post("/{org_id}/select")
def select_workspace(ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """Remember the workspace the portal should reopen."""
    me = db.get(db_models.User, ctx.user_id)
    me.last_org_id = ctx.org_id
    db.commit()
    return {"last_org_id": ctx.org_id}


@router.get("/{org_id}/activity")
def workspace_activity(limit: int = 100, ctx: OrgContext = Depends(org_access("audit.view")),
                       db: Session = Depends(get_db)):
    """Audit log for owners and admins (audit.view is not covered by viewers' "*.read")."""
    rows = (db.query(db_models.AuditEvent).filter(db_models.AuditEvent.org_id == ctx.org_id)
            .order_by(db_models.AuditEvent.created_at.desc(), db_models.AuditEvent.id.desc())
            .limit(max(1, min(limit, 500))).all())
    return [event_out(e) for e in rows]


@router.get("/{org_id}/jobs/{job_id}")
def job_status(job_id: str, ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """Progress of background work started in this workspace (DESIGN.md §7)."""
    job = db.get(db_models.Job, job_id)
    if job is None or job.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_out(job)


class AlertSettings(BaseModel):
    # {"uptime.down": false, ...}; events left out keep their current setting
    events: dict[str, bool]


def _my_membership(db: Session, ctx: OrgContext) -> "db_models.Membership":
    return (db.query(db_models.Membership)
            .filter(db_models.Membership.org_id == ctx.org_id, db_models.Membership.user_id == ctx.user_id).one())


def _alerts_out(db: Session, membership_id: int) -> list[dict]:
    prefs = {p.event_key: p.email for p in db.query(db_models.NotificationPref)
             .filter(db_models.NotificationPref.membership_id == membership_id)}
    return [{"event_key": key, "app": ev["app"], "app_name": APPS[ev["app"]]["name"], "label": ev["label"],
             "email": prefs.get(key, True)} for key, ev in NOTIFICATION_EVENTS.items() if APPS[ev["app"]]["available"]]


@router.get("/{org_id}/notifications")
def my_alert_settings(ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """The caller's own email alert choices for this workspace (any role)."""
    return _alerts_out(db, _my_membership(db, ctx).id)


@router.put("/{org_id}/notifications")
def update_my_alert_settings(payload: AlertSettings, ctx: OrgContext = Depends(org_access("org.read")),
                             db: Session = Depends(get_db)):
    unknown = sorted(set(payload.events) - set(NOTIFICATION_EVENTS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown alerts: {', '.join(unknown)}")
    membership = _my_membership(db, ctx)
    for key, on in payload.events.items():
        row = db.get(db_models.NotificationPref, (membership.id, key))
        if row is None:
            db.add(db_models.NotificationPref(membership_id=membership.id, event_key=key, email=on))
        else:
            row.email = on
    audit_ctx(db, ctx, "notifications.updated", target_id=ctx.user_id, metadata=payload.events)
    db.commit()
    return _alerts_out(db, membership.id)
