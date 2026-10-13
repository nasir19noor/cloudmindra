"""Workspaces (organizations): access checks and shared helpers (DESIGN.md §4).

Modules check access only through org_access() and read workspace data only through
the functions here, never by querying core tables themselves (DESIGN.md §6 rule 7).
"""
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.catalog import has_permission
from core.auth import client_ip, require_user
from core.database import get_db
from core import models as db_models
@dataclass(frozen=True)
class OrgContext:
    org_id: str
    user_id: str
    role: str
    email: str
    ip: str | None = None  # for the audit log


def org_access(action: str):
    """Dependency for /api/orgs/{org_id}/… routes: member of the workspace and allowed `action`."""

    def dependency(org_id: str, request: Request, user: dict = Depends(require_user),
                   db: Session = Depends(get_db)) -> OrgContext:
        membership = (
            db.query(db_models.Membership)
            .filter(db_models.Membership.org_id == org_id, db_models.Membership.user_id == user["sub"])
            .first()
        )
        # Same response for "does not exist" and "not yours" so workspace ids cannot be probed
        if membership is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if not has_permission(membership.role, action):
            raise HTTPException(status_code=403, detail="Your role in this workspace does not allow this")
        return OrgContext(org_id=org_id, user_id=user["sub"], role=membership.role, email=user["email"],
                          ip=client_ip(request))

    return dependency


def org_query(db: Session, model, ctx: OrgContext):
    """Query a tenant table scoped to the caller's workspace."""
    return db.query(model).filter(model.org_id == ctx.org_id)


# --- Workspace lifecycle ------------------------------------------------------

def personal_workspace_name(name: str | None, email: str) -> str:
    owner = (name or "").strip() or email.split("@")[0]
    return f"{owner}'s workspace"[:100]


def create_workspace(db: Session, user_id: str, name: str) -> db_models.Organization:
    """Create a workspace owned by user_id. Caller commits."""
    org = db_models.Organization(id=str(uuid.uuid4()), name=name.strip()[:100], created_by=user_id)
    db.add(org)
    # No ORM relationships, so flush explicitly to insert the workspace before its membership
    db.flush()
    db.add(db_models.Membership(org_id=org.id, user_id=user_id, role="owner"))
    db.flush()
    return org


def ensure_workspace(db: Session, user: db_models.User) -> None:
    """Give a user with no workspace a personal one, and keep last_org_id valid. Caller commits."""
    org_ids = [m.org_id for m in db.query(db_models.Membership).filter(db_models.Membership.user_id == user.id)]
    if not org_ids:
        org = create_workspace(db, user.id, personal_workspace_name(user.name, user.email))
        org_ids = [org.id]
    if user.last_org_id not in org_ids:
        user.last_org_id = org_ids[0]


def delete_workspace(db: Session, org_id: str) -> None:
    """Delete a workspace. Caller commits.

    Core rows go now (memberships, invitations, tiers cascade). Modules delete their own
    data when they receive the org.deleted event (DESIGN.md §6 rule 10).
    """
    from core.outbox import emit  # local: core.models imports core.outbox

    db.query(db_models.User).filter(db_models.User.last_org_id == org_id).update({"last_org_id": None})
    db.query(db_models.Organization).filter(db_models.Organization.id == org_id).delete()
    emit(db, db_models.CoreOutbox, "org.deleted", org_id)


def alert_recipients(db: Session, org_id: str, event_key: str | None = None) -> list[str]:
    """Emails of the workspace's members who want this alert. Alerts are on for every role
    unless the member switched that event off (DESIGN.md §4.1)."""
    q = (
        db.query(db_models.User.email)
        .join(db_models.Membership, db_models.Membership.user_id == db_models.User.id)
        .filter(db_models.Membership.org_id == org_id)
    )
    if event_key:
        opted_out = (
            db.query(db_models.NotificationPref.membership_id)
            .filter(db_models.NotificationPref.event_key == event_key, db_models.NotificationPref.email.is_(False))
        )
        q = q.filter(db_models.Membership.id.notin_(opted_out))
    return sorted({email for (email,) in q.all() if email})
