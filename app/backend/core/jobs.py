"""Background jobs in Postgres (DESIGN.md §7).

enqueue() adds a job in the caller's transaction. The worker claims due jobs with
SELECT … FOR UPDATE SKIP LOCKED (safe with several workers), runs the registered
handler, and retries failures with exponential backoff up to max_attempts.
Jobs stuck in "running" (worker crashed) are put back after STUCK_AFTER.
"""
import logging
import os
import socket
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core import models

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=1)

# job type -> fn(db, payload: dict, job: models.Job) -> optional result dict
JOB_HANDLERS: dict[str, Callable[[Session, dict, "models.Job"], dict | None]] = {}


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def job_handler(job_type: str):
    def decorator(fn):
        JOB_HANDLERS[job_type] = fn
        return fn
    return decorator


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db: Session, job_type: str, payload: dict | None = None, *, org_id: str | None = None,
            app_key: str = "core", run_at: datetime | None = None, dedupe_key: str | None = None,
            max_attempts: int = 5, created_by: str | None = None) -> str | None:
    """Queue a job in the caller's transaction. With dedupe_key, a second enqueue is a no-op (returns None)."""
    job_id = str(uuid.uuid4())
    stmt = insert(models.Job).values(
        id=job_id, org_id=org_id, app_key=app_key, type=job_type, payload=payload or {}, status="queued",
        dedupe_key=dedupe_key, run_at=run_at or _now(), attempts=0, max_attempts=max_attempts, created_by=created_by,
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    inserted = db.execute(stmt.returning(models.Job.id), bind_arguments={"mapper": models.Job}).scalar()
    return inserted


def claim(db: Session, limit: int = 10) -> list[str]:
    """Mark up to `limit` due jobs as running for this worker and return their ids."""
    rows = db.execute(text("""
        UPDATE core.jobs SET status = 'running', locked_by = :me, locked_at = now(), attempts = attempts + 1
        WHERE id IN (
            SELECT id FROM core.jobs
            WHERE status = 'queued' AND run_at <= now()
            ORDER BY run_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id
    """), {"me": worker_id(), "limit": limit}, bind_arguments={"mapper": models.Job}).scalars().all()
    db.commit()
    return list(rows)


def run_job(db: Session, job_id: str) -> str:
    """Run one claimed job; returns its final status for this attempt."""
    job = db.get(models.Job, job_id)
    handler = JOB_HANDLERS.get(job.type)
    try:
        if handler is None:
            raise RuntimeError(f"No handler registered for job type {job.type!r}")
        result = handler(db, job.payload or {}, job)
        db.flush()
        job.status, job.result, job.error, job.finished_at = "succeeded", result, None, _now()
        db.commit()
        return "succeeded"
    except Exception as exc:  # noqa: BLE001 - any handler failure is recorded and retried
        db.rollback()
        job = db.get(models.Job, job_id)
        job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"[:4000]
        if job.attempts >= job.max_attempts:
            job.status, job.finished_at = "failed", _now()
            logger.error("Job %s (%s) failed permanently: %s", job.id, job.type, exc)
        else:
            delay = min(timedelta(seconds=30 * 2 ** (job.attempts - 1)), MAX_BACKOFF)
            job.status, job.run_at = "queued", _now() + delay
            logger.warning("Job %s (%s) failed, retry %s/%s in %s: %s",
                           job.id, job.type, job.attempts, job.max_attempts, delay, exc)
        job.locked_by = job.locked_at = None
        db.commit()
        return job.status


def requeue_stuck(db: Session) -> int:
    n = db.execute(text("""
        UPDATE core.jobs SET status = 'queued', locked_by = NULL, locked_at = NULL, run_at = now()
        WHERE status = 'running' AND locked_at < now() - make_interval(secs => :secs)
    """), {"secs": STUCK_AFTER.total_seconds()}, bind_arguments={"mapper": models.Job}).rowcount
    db.commit()
    return n


def enqueue_due_schedules(db: Session) -> int:
    """Turn due schedules into jobs (one per run, deduplicated per schedule and run time)."""
    due = (
        db.query(models.Schedule)
        .filter(models.Schedule.enabled.is_(True), models.Schedule.next_run_at <= _now())
        .with_for_update(skip_locked=True)
        .all()
    )
    for s in due:
        enqueue(db, s.type, s.payload, org_id=s.org_id, app_key=s.app_key,
                dedupe_key=f"schedule:{s.id}:{s.next_run_at.isoformat()}")
        s.last_run_at = _now()
        s.next_run_at = _now() + timedelta(seconds=s.interval_seconds)
    db.commit()
    return len(due)


def job_out(job: "models.Job") -> dict:
    iso = lambda dt: dt.isoformat() if dt else None  # noqa: E731
    return {"id": job.id, "type": job.type, "app_key": job.app_key, "status": job.status, "attempts": job.attempts,
            "max_attempts": job.max_attempts, "result": job.result, "error": (job.error or "").split("\n")[0] or None,
            "run_at": iso(job.run_at), "created_at": iso(job.created_at), "finished_at": iso(job.finished_at)}


# Events relayed from outboxes run as "event" jobs (see core/outbox.py)
@job_handler("event")
def _run_event(db: Session, payload: dict, job) -> dict | None:
    from core.outbox import HANDLERS
    handler = HANDLERS.get(payload["handler"])
    if handler is None:
        raise RuntimeError(f"No event handler {payload['handler']!r}")
    handler(db, payload["event"])
    return None
