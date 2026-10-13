"""Transactional outbox (DESIGN.md §6.1, §7).

Every schema has its own `outbox` table. A module writes an event with emit() in the
same transaction as the data change it describes, so the event exists if and only if
the change was committed. The worker's relay turns each unpublished event into one job
per subscriber (dedupe key "<event id>:<handler>"), then marks the event published.
Delivery is at-least-once: handlers must be idempotent.

Later the relay can publish to SQS/EventBridge instead of core.jobs without changing
emit() callers.
"""
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)


class OutboxMixin:
    """Columns of <schema>.outbox; each schema declares `class XOutbox(OutboxMixin, XBase)`."""
    __tablename__ = "outbox"

    id = Column(String, primary_key=True)  # event id, also the consumers' dedupe key
    event_type = Column(String(60), nullable=False)
    org_id = Column(String, nullable=True, index=True)
    payload = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    published_at = Column(DateTime(timezone=True), nullable=True, index=True)


# Registered outbox models (one per schema) and subscribers
OUTBOXES: list[type] = []
SUBSCRIBERS: dict[str, list[str]] = defaultdict(list)  # event_type -> handler names
HANDLERS: dict[str, Callable[[Session, dict], None]] = {}  # handler name -> fn(db, event)


def register_outbox(model: type) -> type:
    if model not in OUTBOXES:
        OUTBOXES.append(model)
    return model


def subscribe(*event_types: str, name: str | None = None):
    """Decorator: run fn(db, event) as a job for each event of these types."""
    def decorator(fn):
        handler = name or f"{fn.__module__}.{fn.__name__}"
        HANDLERS[handler] = fn
        for event_type in event_types:
            if handler not in SUBSCRIBERS[event_type]:
                SUBSCRIBERS[event_type].append(handler)
        return fn
    return decorator


def emit(db: Session, outbox_model: type, event_type: str, org_id: str | None, payload: dict | None = None) -> str:
    """Record an event in the caller's transaction. Use the outbox of the schema whose data changed."""
    event_id = str(uuid.uuid4())
    db.add(outbox_model(id=event_id, event_type=event_type, org_id=org_id, payload=payload or {}))
    return event_id


def event_dict(row) -> dict:
    return {"id": row.id, "type": row.event_type, "org_id": row.org_id, "payload": row.payload or {},
            "created_at": row.created_at.isoformat() if row.created_at else None}


def relay(db: Session, batch: int = 100) -> int:
    """Turn unpublished events into jobs (one per subscriber). Returns events relayed.
    Locks rows with SKIP LOCKED so several workers can relay in parallel."""
    from core import jobs  # local: jobs imports nothing from here, avoids import order issues

    relayed = 0
    for model in OUTBOXES:
        rows = (
            db.query(model)
            .filter(model.published_at.is_(None))
            .order_by(model.created_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not rows:
            continue
        ids = [row.id for row in rows]
        for row in rows:
            event = event_dict(row)
            for handler in SUBSCRIBERS.get(row.event_type, []):
                jobs.enqueue(db, "event", {"handler": handler, "event": event}, org_id=row.org_id,
                             app_key="events", dedupe_key=f"{row.id}:{handler}")
        # Jobs first, then published_at (they can be different connections with per-module roles):
        # a crash in between re-relays the events and the dedupe keys drop the duplicates,
        # whereas the opposite order could lose events
        db.commit()
        db.query(model).filter(model.id.in_(ids)).update(
            {"published_at": datetime.now(timezone.utc)}, synchronize_session=False)
        db.commit()
        relayed += len(ids)
    return relayed
