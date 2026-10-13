"""Workspace team: invitations and members (DESIGN.md §4.1, §4.2).

- Owners and admins invite by email as admin, member or viewer (never owner).
- Only the SHA-256 of the 7-day token is stored; the raw token exists only in the email.
- Accepting requires signing in with the exact, verified invited address.
- Seats (members + pending invitations) are capped by entitlements.seat_limit().
- A workspace always keeps at least one owner; only owners can grant or remove owner.
"""
import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.catalog import has_permission
from core.auth import require_user
from core.database import get_db
from core.mailer import send_invitation_email
from core.audit import audit, audit_ctx
from core.auth import client_ip
from core.entitlements import seat_limit
from core.orgs import OrgContext, ensure_workspace, org_access
from core import models as db_models
router = APIRouter(tags=["team"])

INVITE_TTL = timedelta(days=7)
InviteRole = Literal["admin", "member", "viewer"]
MemberRole = Literal["owner", "admin", "member", "viewer"]


class InviteCreate(BaseModel):
    email: EmailStr
    role: InviteRole = "member"


class InviteAccept(BaseModel):
    token: str


class MemberUpdate(BaseModel):
    role: MemberRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(dt):
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _pending(db: Session, org_id: str):
    return db.query(db_models.Invitation).filter(
        db_models.Invitation.org_id == org_id,
        db_models.Invitation.accepted_at.is_(None),
        db_models.Invitation.expires_at > _now(),
    )


def _member_count(db: Session, org_id: str) -> int:
    return db.query(db_models.Membership).filter(db_models.Membership.org_id == org_id).count()


def _owner_count(db: Session, org_id: str) -> int:
    return (db.query(db_models.Membership)
            .filter(db_models.Membership.org_id == org_id, db_models.Membership.role == "owner").count())


def _invite_link(token: str) -> str:
    return f"{os.getenv('FRONTEND_URL', 'https://cloudmindra.com').rstrip('/')}/portal/invite?token={token}"


def _invite_out(inv: db_models.Invitation) -> dict:
    return {"id": inv.id, "email": inv.email, "role": inv.role,
            "expires_at": _iso(inv.expires_at), "created_at": _iso(inv.created_at)}


def _send_invite(to: str, inviter: str, workspace: str, role: str, token: str, expires: datetime) -> bool:
    return send_invitation_email(
        to,
        f"{inviter} invited you to {workspace} on CloudMindra",
        f"{inviter} invited you to join the workspace \"{workspace}\" on CloudMindra as {role}.\n\n"
        f"Accept the invitation:\n{_invite_link(token)}\n\n"
        f"Sign in with this email address ({to}) to accept. The link expires on {expires:%Y-%m-%d}.\n\n"
        f"If you weren't expecting this, you can ignore this email.\n",
    )


# --- Invitations (owners/admins) -------------------------------------------------

@router.get("/api/orgs/{org_id}/invitations")
def list_invitations(ctx: OrgContext = Depends(org_access("members.manage")), db: Session = Depends(get_db)):
    rows = _pending(db, ctx.org_id).order_by(db_models.Invitation.created_at).all()
    return [_invite_out(i) for i in rows]


@router.post("/api/orgs/{org_id}/invitations", status_code=201)
def invite(payload: InviteCreate, ctx: OrgContext = Depends(org_access("members.manage")),
           db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    org = db.get(db_models.Organization, ctx.org_id)

    already_member = (
        db.query(db_models.Membership)
        .join(db_models.User, db_models.User.id == db_models.Membership.user_id)
        .filter(db_models.Membership.org_id == ctx.org_id, func.lower(db_models.User.email) == email)
        .first()
    )
    if already_member:
        raise HTTPException(status_code=409, detail=f"{email} is already in this workspace")

    # Inviting the same address again refreshes the invitation (new link, new expiry, new role)
    existing = _pending(db, ctx.org_id).filter(db_models.Invitation.email == email).first()
    if existing is None:
        seats = _member_count(db, ctx.org_id) + _pending(db, ctx.org_id).count()
        limit = seat_limit(db, org)
        if seats >= limit:
            raise HTTPException(status_code=402, detail=f"This workspace has {limit} seats, including pending invitations. "
                                                        "Remove someone or cancel an invitation first.")

    token = secrets.token_urlsafe(32)
    expires = _now() + INVITE_TTL
    if existing:
        inv = existing
        inv.role, inv.token_hash, inv.expires_at, inv.invited_by = payload.role, _hash(token), expires, ctx.user_id
    else:
        inv = db_models.Invitation(id=str(uuid.uuid4()), org_id=ctx.org_id, email=email, role=payload.role,
                                   token_hash=_hash(token), invited_by=ctx.user_id, expires_at=expires)
        db.add(inv)
    audit_ctx(db, ctx, "member.invited", target_id=inv.id,
              metadata={"email": email, "role": payload.role, "resent": existing is not None})
    db.commit()

    inviter = db.get(db_models.User, ctx.user_id)
    # Sent in the request (not a background task) so the inviter learns when delivery fails,
    # e.g. SES still in sandbox mode. Then they get the link to share themselves.
    sent = _send_invite(email, (inviter.name or inviter.email), org.name, payload.role, token, expires)
    out = {**_invite_out(inv), "email_sent": sent}
    if not sent:
        out["invite_link"] = _invite_link(token)
    return out


@router.delete("/api/orgs/{org_id}/invitations/{invitation_id}", status_code=204)
def cancel_invitation(invitation_id: str, ctx: OrgContext = Depends(org_access("members.manage")),
                      db: Session = Depends(get_db)):
    inv = db.get(db_models.Invitation, invitation_id)
    if inv is None or inv.org_id != ctx.org_id or inv.accepted_at is not None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    audit_ctx(db, ctx, "invitation.cancelled", target_id=inv.id, metadata={"email": inv.email})
    db.delete(inv)
    db.commit()


# --- Invitee side ----------------------------------------------------------------------

def _find_invitation(db: Session, token: str) -> db_models.Invitation:
    inv = db.query(db_models.Invitation).filter(db_models.Invitation.token_hash == _hash(token)).first()
    if inv is None:
        raise HTTPException(status_code=404, detail="This invitation link is not valid. It may have been cancelled or replaced.")
    return inv


@router.get("/api/invitations/preview")
def preview(token: str, db: Session = Depends(get_db)):
    """What the link is for, shown before sign-in. Only someone holding the emailed token can call it."""
    inv = _find_invitation(db, token)
    org = db.get(db_models.Organization, inv.org_id)
    inviter = db.get(db_models.User, inv.invited_by) if inv.invited_by else None
    status = "accepted" if inv.accepted_at else "expired" if _aware(inv.expires_at) <= _now() else "pending"
    return {"workspace": org.name if org else None, "role": inv.role, "email": inv.email,
            "invited_by": (inviter.name or inviter.email) if inviter else None,
            "expires_at": _iso(inv.expires_at), "status": status}


@router.post("/api/invitations/accept")
def accept(payload: InviteAccept, request: Request, user: dict = Depends(require_user), db: Session = Depends(get_db)):
    inv = _find_invitation(db, payload.token)
    if inv.accepted_at is not None:
        raise HTTPException(status_code=410, detail="This invitation has already been used")
    if _aware(inv.expires_at) <= _now():
        raise HTTPException(status_code=410, detail="This invitation has expired. Ask for a new one.")
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Please sign in again with a verified email address")
    if user["email"].strip().lower() != inv.email:
        raise HTTPException(status_code=403, detail=f"This invitation was sent to {inv.email}. "
                                                    f"Sign in with that address to accept it.")

    me = db.get(db_models.User, user["sub"])
    membership = (db.query(db_models.Membership)
                  .filter(db_models.Membership.org_id == inv.org_id, db_models.Membership.user_id == me.id).first())
    if membership is None:
        db.add(db_models.Membership(org_id=inv.org_id, user_id=me.id, role=inv.role))
    inv.accepted_at = _now()
    me.last_org_id = inv.org_id
    audit(db, "member.joined", org_id=inv.org_id, actor_id=me.id, actor_email=me.email, target_id=me.id,
          metadata={"role": membership.role if membership else inv.role, "invitation_id": inv.id}, ip=client_ip(request))
    db.commit()
    org = db.get(db_models.Organization, inv.org_id)
    return {"id": org.id, "name": org.name, "role": membership.role if membership else inv.role}


# --- Members -------------------------------------------------------------------------------

@router.get("/api/orgs/{org_id}/members")
def list_members(ctx: OrgContext = Depends(org_access("members.read")), db: Session = Depends(get_db)):
    org = db.get(db_models.Organization, ctx.org_id)
    rows = (
        db.query(db_models.Membership, db_models.User)
        .join(db_models.User, db_models.User.id == db_models.Membership.user_id)
        .filter(db_models.Membership.org_id == ctx.org_id)
        .order_by(db_models.Membership.created_at)
        .all()
    )
    return {
        "members": [{"user_id": u.id, "email": u.email, "name": u.name, "role": m.role,
                     "is_self": u.id == ctx.user_id, "joined_at": _iso(m.created_at)} for m, u in rows],
        "seats": {"used": len(rows) + _pending(db, ctx.org_id).count(), "limit": seat_limit(db, org)},
        "can_manage": has_permission(ctx.role, "members.manage"),
    }


def _target(db: Session, ctx: OrgContext, user_id: str) -> db_models.Membership:
    m = (db.query(db_models.Membership)
         .filter(db_models.Membership.org_id == ctx.org_id, db_models.Membership.user_id == user_id).first())
    if m is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return m


@router.patch("/api/orgs/{org_id}/members/{user_id}")
def change_role(user_id: str, payload: MemberUpdate, ctx: OrgContext = Depends(org_access("members.manage")),
                db: Session = Depends(get_db)):
    m = _target(db, ctx, user_id)
    touches_owner = payload.role == "owner" or m.role == "owner"
    if touches_owner and not has_permission(ctx.role, "org.transfer"):
        raise HTTPException(status_code=403, detail="Only an owner can grant or remove the owner role")
    if m.role == "owner" and payload.role != "owner" and _owner_count(db, ctx.org_id) <= 1:
        raise HTTPException(status_code=400, detail="A workspace needs at least one owner. Make someone else owner first.")
    if m.role != payload.role:
        audit_ctx(db, ctx, "member.role_changed", target_id=user_id, metadata={"from": m.role, "to": payload.role})
    m.role = payload.role
    db.commit()
    return {"user_id": user_id, "role": m.role}


@router.delete("/api/orgs/{org_id}/members/{user_id}", status_code=204)
def remove_member(user_id: str, ctx: OrgContext = Depends(org_access("org.read")), db: Session = Depends(get_db)):
    """Remove someone (owners/admins), or leave the workspace yourself (anyone)."""
    leaving = user_id == ctx.user_id
    if not leaving and not has_permission(ctx.role, "members.manage"):
        raise HTTPException(status_code=403, detail="Your role in this workspace does not allow this")
    m = _target(db, ctx, user_id)
    if m.role == "owner":
        if not leaving and not has_permission(ctx.role, "org.transfer"):
            raise HTTPException(status_code=403, detail="Only an owner can remove another owner")
        if _owner_count(db, ctx.org_id) <= 1:
            raise HTTPException(status_code=400, detail="A workspace needs at least one owner. "
                                                        "Make someone else owner first, or delete the workspace.")
    removed = db.get(db_models.User, user_id)
    audit_ctx(db, ctx, "member.left" if leaving else "member.removed", target_id=user_id,
              metadata={"email": removed.email, "role": m.role})
    db.delete(m)
    db.flush()
    # Someone left with no workspace gets a fresh personal one, like on first login
    ensure_workspace(db, removed)
    db.commit()
