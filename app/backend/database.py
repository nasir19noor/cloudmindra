from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from db_models import ContactSubmission, BlogPost, Service, PageVisit, User  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # create_all never alters existing tables, so add columns introduced later
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    if "is_admin" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))

    seed_admins()


def seed_admins():
    """Grant admin to existing users listed in ADMIN_EMAIL; new ones get it on first login."""
    from cognito_auth import seed_admin_emails
    from db_models import User

    emails = seed_admin_emails()
    if not emails:
        return
    db = SessionLocal()
    try:
        users = db.query(User).filter(func.lower(User.email).in_(emails), User.is_admin.is_(False)).all()
        for user in users:
            user.is_admin = True
        db.commit()
    finally:
        db.close()
