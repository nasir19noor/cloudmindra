"""Platform health for /admin (DESIGN.md §7): job queue, outbox backlog, and module signals.

Modules register a HEALTH_PROVIDERS[app] = fn(db) -> dict, so core never queries module
tables (DESIGN.md §6 rule 9). A provider may return "warning": "<reason>" to flag a problem.
"""
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from core import models
from core.outbox import OUTBOXES

HEALTH_PROVIDERS: dict[str, Callable[[Session], dict]] = {}

QUEUE_WARN_SECONDS = 300  # a due job waiting longer than this means no worker is picking jobs up


def _age(dt: datetime | None, now: datetime) -> int | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((now - dt).total_seconds()))


def system_health(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    warnings: list[str] = []

    counts = dict(db.query(models.Job.status, func.count(models.Job.id)).group_by(models.Job.status).all())
    oldest_due = (db.query(func.min(models.Job.run_at))
                  .filter(models.Job.status == "queued", models.Job.run_at <= now).scalar())
    failed_24h = (db.query(func.count(models.Job.id))
                  .filter(models.Job.status == "failed", models.Job.finished_at >= now - timedelta(days=1)).scalar())
    jobs = {
        "counts": {s: counts.get(s, 0) for s in ("queued", "running", "succeeded", "failed", "cancelled")},
        "oldest_due_seconds": _age(oldest_due, now),
        "failed_24h": failed_24h,
    }
    if jobs["oldest_due_seconds"] is not None and jobs["oldest_due_seconds"] > QUEUE_WARN_SECONDS:
        warnings.append(f"Jobs have been waiting {jobs['oldest_due_seconds'] // 60} min — is the worker running?")
    if failed_24h:
        warnings.append(f"{failed_24h} job(s) failed in the last 24 hours")

    outbox = []
    for model in OUTBOXES:
        backlog, oldest = (db.query(func.count(model.id), func.min(model.created_at))
                           .filter(model.published_at.is_(None)).one())
        age = _age(oldest, now)
        outbox.append({"table": model.__table__.fullname, "unpublished": backlog, "oldest_seconds": age})
        if age is not None and age > QUEUE_WARN_SECONDS:
            warnings.append(f"{model.__table__.fullname} has events waiting {age // 60} min — is the worker running?")

    modules = {}
    for key, provider in HEALTH_PROVIDERS.items():
        try:
            modules[key] = provider(db)
        except Exception as exc:  # noqa: BLE001 - a broken provider must not hide the rest
            modules[key] = {"warning": f"health check failed: {type(exc).__name__}"}
        if modules[key].get("warning"):
            warnings.append(f"{key}: {modules[key]['warning']}")

    return {"status": "warning" if warnings else "ok", "warnings": warnings, "jobs": jobs, "outbox": outbox,
            "modules": modules, "checked_at": now.isoformat()}

