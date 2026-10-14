"""Uptime's registrations with core: event handlers and its usage provider.

Handlers run as jobs (at-least-once, retried on failure), so they must be idempotent.
"""
from sqlalchemy.orm import Session

from core.entitlements import USAGE_PROVIDERS
from core.health import HEALTH_PROVIDERS
from core.notify import notify
from core.outbox import subscribe
from apps.uptime import models as db_models


@subscribe("uptime.down", "uptime.recovered", "uptime.ssl_expiring", name="uptime.alert_members")
def alert_members(db: Session, event: dict) -> None:
    """Email the members who want this alert (one retried job per recipient)."""
    p = event["payload"]
    notify(db, event["org_id"], event["type"], p["subject"], p["body"], dedupe=event["id"])


@subscribe("org.deleted", name="uptime.delete_workspace_data")
def delete_workspace_data(db: Session, event: dict) -> None:
    """Remove a deleted workspace's monitors, history and outbox rows (safe to run twice)."""
    org_id = event["org_id"]
    ids = [m_id for (m_id,) in db.query(db_models.Monitor.id).filter(db_models.Monitor.org_id == org_id)]
    if ids:
        db.query(db_models.MonitorCheck).filter(db_models.MonitorCheck.monitor_id.in_(ids)).delete(synchronize_session=False)
        db.query(db_models.Monitor).filter(db_models.Monitor.id.in_(ids)).delete(synchronize_session=False)
    db.query(db_models.UptimeOutbox).filter(
        db_models.UptimeOutbox.org_id == org_id, db_models.UptimeOutbox.published_at.isnot(None)
    ).delete(synchronize_session=False)


def _usage(db: Session, org_id: str) -> dict[str, int]:
    return {"uptime.monitors": db.query(db_models.Monitor).filter(db_models.Monitor.org_id == org_id).count()}


# Core reads module usage through this provider, never by querying uptime tables
USAGE_PROVIDERS["uptime"] = _usage


OVERDUE_GRACE_MINUTES = 10  # how late past its own interval a check may be before /admin warns


def _health(db: Session) -> dict:
    """For /admin: is the uptime loop keeping up? (DESIGN.md §7)"""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    active = db.query(db_models.Monitor).filter(db_models.Monitor.is_active.is_(True)).all()
    overdue = 0
    for m in active:
        since = m.last_checked_at or m.created_at
        if since is not None and now - since > timedelta(minutes=m.interval_minutes + OVERDUE_GRACE_MINUTES):
            overdue += 1
    last = max((m.last_checked_at for m in active if m.last_checked_at), default=None)
    out = {"active_monitors": len(active), "overdue_monitors": overdue, "last_check_at": last.isoformat() if last else None}
    if overdue:
        out["warning"] = f"{overdue} monitor(s) are overdue for a check — is the worker running?"
    return out


HEALTH_PROVIDERS["uptime"] = _health
