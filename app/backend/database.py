"""Database engines and sessions.

Each schema has its own declarative base and engine so every module can connect
as its own Postgres role (see DESIGN.md §6.1). When the per-schema URLs are not
set, all schemas share DATABASE_URL and a single engine.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine, func
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# schema -> env var holding the URL of that schema's role
SCHEMA_URL_ENV = {
    "core": "DATABASE_URL_CORE",
    "uptime": "DATABASE_URL_UPTIME",
    "site": "DATABASE_URL_SITE",
}


# Index names without the schema prefix, matching the migrations (ix_<table>_<column>)
NAMING = {"ix": "ix_%(table_name)s_%(column_0_name)s"}


class CoreBase(DeclarativeBase):
    metadata = MetaData(schema="core", naming_convention=NAMING)


class UptimeBase(DeclarativeBase):
    metadata = MetaData(schema="uptime", naming_convention=NAMING)


class SiteBase(DeclarativeBase):
    metadata = MetaData(schema="site", naming_convention=NAMING)


BASES = {"core": CoreBase, "uptime": UptimeBase, "site": SiteBase}

_engines: dict[str, object] = {}


def _engine_for(url: str):
    # Share one engine (and pool) between schemas that use the same URL
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True)
    return _engines[url]


def schema_url(schema: str) -> str:
    return os.getenv(SCHEMA_URL_ENV[schema]) or DATABASE_URL


engine = _engine_for(DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    binds={base: _engine_for(schema_url(schema)) for schema, base in BASES.items()},
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Runtime setup after migrations. Schema changes live in Alembic (migrate.py)."""
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
