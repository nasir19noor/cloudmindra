"""Schema uptime: Uptime Monitor tables. org_id / created_by refer to core rows without foreign keys."""
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.sql import func

from core.database import UptimeBase
from core.outbox import OutboxMixin, register_outbox


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


class UptimeOutbox(OutboxMixin, UptimeBase):
    """Events about uptime data (monitor down / recovered / SSL expiring)."""


register_outbox(UptimeOutbox)
