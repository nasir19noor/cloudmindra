"""ORM models, grouped by Postgres schema (DESIGN.md §6.1, §9).

Foreign keys only point inside the same schema. Columns that refer to another
schema (org_id, created_by, …) are plain indexed values.
"""
from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Float, ForeignKey, UniqueConstraint
from sqlalchemy.sql import false, func

from database import CoreBase, SiteBase, UptimeBase


# --- schema site: marketing website ---------------------------------------

class ContactSubmission(SiteBase):
    __tablename__ = "contact_submissions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    company = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="new")


class BlogPost(SiteBase):
    __tablename__ = "blog_posts"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    content = Column(Text, nullable=False)
    excerpt = Column(String, nullable=True)
    author = Column(String, default="CloudMindra")
    published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Service(SiteBase):
    __tablename__ = "services"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    icon = Column(String, nullable=True)
    order = Column(Integer, default=0)


class PageVisit(SiteBase):
    __tablename__ = "page_visits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    visitor_ip = Column(String(45), index=True)
    user_agent = Column(Text)
    os = Column(String(50))
    device_type = Column(String(20))
    browser = Column(String(50))
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    path = Column(String(500), index=True)
    referrer = Column(Text, nullable=True)
    visited_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


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


# --- schema uptime: Uptime Monitor module ------------------------------------

class Monitor(UptimeBase):
    __tablename__ = "monitors"

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=False, index=True)  # core.organizations.id, no cross-schema FK
    created_by = Column(String, nullable=True, index=True)  # core.users.id, no cross-schema FK
    name = Column(String(100), nullable=False)
    url = Column(String(2048), nullable=False)
    interval_minutes = Column(Integer, nullable=False, default=5)
    is_active = Column(Boolean, nullable=False, default=True)
    # pending (never checked), up, down
    status = Column(String(10), nullable=False, default="pending")
    consecutive_failures = Column(Integer, nullable=False, default=0)
    down_since = Column(DateTime(timezone=True), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_response_ms = Column(Integer, nullable=True)
    last_error = Column(String(300), nullable=True)
    ssl_expires_at = Column(DateTime(timezone=True), nullable=True)
    ssl_checked_at = Column(DateTime(timezone=True), nullable=True)
    # Expiry date we last warned about, so each certificate triggers one alert
    ssl_alerted_for = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MonitorCheck(UptimeBase):
    __tablename__ = "checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(String, ForeignKey("uptime.monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    checked_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ok = Column(Boolean, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_ms = Column(Integer, nullable=True)
    error = Column(String(300), nullable=True)
