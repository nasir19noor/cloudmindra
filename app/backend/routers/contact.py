from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import uuid

from database import get_db
from models import ContactRequest, ContactResponse
import db_models

router = APIRouter(prefix="/api/contact", tags=["contact"])


@router.post("", response_model=ContactResponse)
async def submit_contact(request: ContactRequest, db: Session = Depends(get_db)):
    submission = db_models.ContactSubmission(
        id=str(uuid.uuid4()),
        name=request.name,
        email=request.email,
        company=request.company,
        message=request.message,
        status="new",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return ContactResponse(
        id=submission.id,
        name=submission.name,
        email=submission.email,
        company=submission.company,
        message=submission.message,
        created_at=submission.created_at,
        status=submission.status,
    )


@router.get("", response_model=list[ContactResponse])
async def list_contacts(db: Session = Depends(get_db)):
    submissions = db.query(db_models.ContactSubmission).order_by(
        db_models.ContactSubmission.created_at.desc()
    ).all()
    return [
        ContactResponse(
            id=s.id, name=s.name, email=s.email, company=s.company,
            message=s.message, created_at=s.created_at, status=s.status,
        )
        for s in submissions
    ]
