"""Audit log: who did what (DESIGN.md §7). Written in the caller's transaction."""
from sqlalchemy.orm import Session

from core import models


def audit(db: Session, action: str, *, org_id: str | None = None, actor_id: str | None = None,
          actor_email: str | None = None, target_id: str | None = None, app_key: str | None = None,
          metadata: dict | None = None, ip: str | None = None) -> None:
    """Record an action such as "member.invited" or "uptime.monitor.deleted"."""
    db.add(models.AuditEvent(org_id=org_id, actor_user_id=actor_id, actor_email=actor_email, action=action,
                             target_id=target_id, app_key=app_key, details=metadata or {}, ip=ip))


def audit_ctx(db: Session, ctx, action: str, *, target_id: str | None = None, app_key: str | None = None,
              metadata: dict | None = None, ip: str | None = None) -> None:
    """audit() for a request made inside a workspace (OrgContext carries the caller and IP)."""
    audit(db, action, org_id=ctx.org_id, actor_id=ctx.user_id, actor_email=ctx.email, target_id=target_id,
          app_key=app_key, metadata=metadata, ip=ip or ctx.ip)


def event_out(e: "models.AuditEvent") -> dict:
    return {"id": e.id, "action": e.action, "actor": e.actor_email, "target_id": e.target_id, "app_key": e.app_key,
            "details": e.details or {}, "ip": e.ip, "org_id": e.org_id,
            "created_at": e.created_at.isoformat() if e.created_at else None}
