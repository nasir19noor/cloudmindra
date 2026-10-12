from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Float, ForeignKey
from sqlalchemy.sql import false, func
from database import Base


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    company = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="new")


class BlogPost(Base):
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


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)  # Cognito "sub"
    email = Column(String, nullable=False, index=True)
    name = Column(String, nullable=True)
    provider = Column(String(50), nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False, server_default=false())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    icon = Column(String, nullable=True)
    order = Column(Integer, default=0)


class PageVisit(Base):
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


class Monitor(Base):
    __tablename__ = "monitors"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
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


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(String, ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True)
    checked_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ok = Column(Boolean, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_ms = Column(Integer, nullable=True)
    error = Column(String(300), nullable=True)
