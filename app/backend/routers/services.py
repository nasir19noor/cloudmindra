from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import ServiceResponse
import db_models

router = APIRouter(prefix="/api/services", tags=["services"])

DEFAULT_SERVICES = [
    {"id": "1", "title": "Cloud Infrastructure", "description": "AWS, GCP, and Azure architecture design, migration, and management. We build scalable, cost-effective cloud environments tailored to your business.", "icon": "cloud", "order": 1},
    {"id": "2", "title": "AI & Machine Learning", "description": "Custom AI solutions, model deployment, and LLM integration. From chatbots to predictive analytics, we bring AI into your workflows.", "icon": "brain", "order": 2},
    {"id": "3", "title": "DevOps & Automation", "description": "CI/CD pipelines, Infrastructure as Code, container orchestration, and monitoring. We automate your development lifecycle end to end.", "icon": "rocket", "order": 3},
    {"id": "4", "title": "Data Engineering", "description": "Data pipelines, analytics platforms, and data lake architecture. We help you collect, process, and derive insights from your data.", "icon": "database", "order": 4},
    {"id": "5", "title": "Cloud Security", "description": "IAM strategy, compliance frameworks, vulnerability assessment, and security automation. We protect your cloud infrastructure.", "icon": "shield", "order": 5},
    {"id": "6", "title": "Consulting", "description": "Cloud strategy, cost optimization, architecture review, and technology roadmap. We guide your cloud journey from planning to execution.", "icon": "lightbulb", "order": 6},
]


@router.get("", response_model=list[ServiceResponse])
async def list_services(db: Session = Depends(get_db)):
    services = db.query(db_models.Service).order_by(db_models.Service.order).all()
    if services:
        return [
            ServiceResponse(
                id=s.id, title=s.title, description=s.description,
                icon=s.icon, order=s.order,
            )
            for s in services
        ]
    return [ServiceResponse(**s) for s in DEFAULT_SERVICES]
