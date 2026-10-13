"""Core schema models: identity, workspaces, tiers and platform services (DESIGN.md §9).

Foreign keys only point inside the same schema; module tables refer to core rows by plain columns.
"""
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Float, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import false, func

from core.database import CoreBase
from core.outbox import OutboxMixin, register_outbox


# --- schema core: identity and workspaces ----------------------------------

class User(CoreBase):
    __tablename__ = "users"

    id = Column(String, primary_key=True)  # Cognito "sub"
    email = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    provider = Column(String(50), nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False, server_default=false())
    # Workspace the portal reopens; plain column to avoid a users <-> organizations cycle
    last_org_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class Organization(CoreBase):
    """A workspace. Called "organization" in code, "workspace" in the UI."""
    __tablename__ = "organizations"

    id = Column(String, primary_key=True)
    name = Column(String(100), nullable=False)
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")
    member_limit = Column(Integer, nullable=True)  # platform-admin override
    created_by = Column(String, ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Membership(CoreBase):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String, ForeignKey("core.organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(10), nullable=False)  # owner | admin | member | viewer
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Invitation(CoreBase):
    """Email invitations (API arrives in phase 4)."""
    __tablename__ = "invitations"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("core.organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, nullable=False)  # lowercased
    role = Column(String(10), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    invited_by = Column(String, ForeignKey("core.users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OrgApp(CoreBase):
    """A workspace's tier for one module. No row means Free with catalog defaults."""
    __tablename__ = "org_apps"

    org_id = Column(String, ForeignKey("core.organizations.id", ondelete="CASCADE"), primary_key=True)
    app_key = Column(String(20), primary_key=True)
    tier = Column(String(10), nullable=False, default="free", server_default="free")  # free | pro
    status = Column(String(10), nullable=False, default="active", server_default="active")  # active | trial | past_due | cancelled
    limits = Column(JSONB, nullable=True)  # per-workspace overrides, e.g. {"uptime.monitors": 200}
    pro_since = Column(DateTime(timezone=True), nullable=True)
    pro_until = Column(DateTime(timezone=True), nullable=True)  # NULL = no end date
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UsageCounter(CoreBase):
    """Monthly usage for "*.per_month" limits (DESIGN.md §5)."""
    __tablename__ = "usage_counters"

    org_id = Column(String, ForeignKey("core.organizations.id", ondelete="CASCADE"), primary_key=True)
    metric = Column(String(50), primary_key=True)
    period = Column(String(7), primary_key=True)  # "YYYY-MM" (UTC)
    count = Column(Integer, nullable=False, default=0, server_default="0")


# --- Platform services (DESIGN.md §7) -------------------------------------------------

class Job(CoreBase):
    """Background job; see core/jobs.py."""
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_at", "status", "run_at"),)

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=True, index=True)
    app_key = Column(String(20), nullable=False)
    type = Column(String(60), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(10), nullable=False, default="queued")  # queued | running | succeeded | failed | cancelled
    dedupe_key = Column(String(200), nullable=True, unique=True)
    run_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    locked_by = Column(String(100), nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)


class Schedule(CoreBase):
    """Repeating job: enqueued every interval_seconds."""
    __tablename__ = "schedules"

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=True, index=True)
    app_key = Column(String(20), nullable=False)
    type = Column(String(60), nullable=False)
    payload = Column(JSONB, nullable=False, default=dict)
    interval_seconds = Column(Integer, nullable=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(CoreBase):
    """Who did what; see core/audit.py. `details` is the DESIGN's "metadata" (a reserved name in SQLAlchemy)."""
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String, nullable=True, index=True)
    actor_user_id = Column(String, nullable=True)
    actor_email = Column(String, nullable=True)
    app_key = Column(String(20), nullable=True)
    action = Column(String(60), nullable=False)
    target_id = Column(String, nullable=True)
    details = Column(JSONB, nullable=False, default=dict)
    ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class CoreOutbox(OutboxMixin, CoreBase):
    """Events about core data (workspaces, members); see core/outbox.py."""


register_outbox(CoreOutbox)
