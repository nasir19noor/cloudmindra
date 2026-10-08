from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text, Float
from sqlalchemy.sql import func
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
