from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import BlogPostResponse
import db_models

router = APIRouter(prefix="/api/blog", tags=["blog"])


@router.get("", response_model=list[BlogPostResponse])
async def list_posts(db: Session = Depends(get_db)):
    posts = db.query(db_models.BlogPost).filter(
        db_models.BlogPost.published == True
    ).order_by(db_models.BlogPost.created_at.desc()).all()
    return [
        BlogPostResponse(
            id=p.id, title=p.title, slug=p.slug, content=p.content,
            excerpt=p.excerpt, author=p.author, published=p.published,
            created_at=p.created_at, updated_at=p.updated_at,
        )
        for p in posts
    ]


@router.get("/{slug}", response_model=BlogPostResponse)
async def get_post(slug: str, db: Session = Depends(get_db)):
    post = db.query(db_models.BlogPost).filter(
        db_models.BlogPost.slug == slug,
        db_models.BlogPost.published == True,
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return BlogPostResponse(
        id=post.id, title=post.title, slug=post.slug, content=post.content,
        excerpt=post.excerpt, author=post.author, published=post.published,
        created_at=post.created_at, updated_at=post.updated_at,
    )
