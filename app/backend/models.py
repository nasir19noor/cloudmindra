from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    company: Optional[str] = Field(None, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)


class ContactResponse(BaseModel):
    id: str
    name: str
    email: str
    company: Optional[str] = None
    message: str
    created_at: datetime
    status: str


class BlogPostResponse(BaseModel):
    id: str
    title: str
    slug: str
    content: str
    excerpt: Optional[str] = None
    author: str
    published: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class ServiceResponse(BaseModel):
    id: str
    title: str
    description: str
    icon: Optional[str] = None
    order: int
