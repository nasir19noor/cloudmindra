import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cognito_auth import require_user
from database import get_db
from entitlements import free_workspace_limit, modules_overview, owned_free_workspace_count
from orgs import OrgContext, create_workspace, delete_workspace, org_access
import db_models

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
def create(payload: WorkspaceCreate, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    me = _current_user(db, user)
    # Only workspaces with no Pro module count (DESIGN.md §4.1)
    limit = free_workspace_limit()
    if owned_free_workspace_count(db, me.id) >= limit:
        raise HTTPException(status_code=403, detail=f"You can own up to {limit} workspaces without a Pro module. "
                                                    "Upgrade one of them, or contact CloudMindra.")
    org = create_workspace(db, me.id, payload.name)
    me.last_org_id = org.id
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
    if payload.name is not None:
        org.name = payload.name.strip()
    if payload.currency is not None:
        currency = payload.currency.strip().upper()
        if not CURRENCY.match(currency):
            raise HTTPException(status_code=422, detail="Currency must be a 3-letter ISO code, e.g. USD or IDR")
        org.currency = currency
    db.commit()
    return _workspace_out(org, ctx.role)


@router.delete("/{org_id}", status_code=204)
def remove_workspace(ctx: OrgContext = Depends(org_access("org.delete")), db: Session = Depends(get_db)):
    mine = db.query(db_models.Membership).filter(db_models.Membership.user_id == ctx.user_id).count()
    if mine <= 1:
        raise HTTPException(status_code=400, detail="You cannot delete your only workspace")
    delete_workspace(db, ctx.org_id)
    db.commit()


@router.post("/{org_id}/select")
def select_workspace(ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """Remember the workspace the portal should reopen."""
    me = db.get(db_models.User, ctx.user_id)
    me.last_org_id = ctx.org_id
    db.commit()
    return {"last_org_id": ctx.org_id}
