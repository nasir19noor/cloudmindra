from sqlalchemy import Column, String, DateTime, Integer, Boolean, Text
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
