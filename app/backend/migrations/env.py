import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Imported so autogenerate can compare against every schema's models
import db_models  # noqa: E402,F401
from database import BASES  # noqa: E402

target_metadata = [base.metadata for base in BASES.values()]


def migration_url() -> str:
    # The migration role owns every schema; app roles only get table privileges
    url = os.getenv("DATABASE_MIGRATION_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL (or DATABASE_MIGRATION_URL) to run migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(url=migration_url(), target_metadata=target_metadata, include_schemas=True,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = create_engine(migration_url(), poolclass=pool.NullPool)
        with engine.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
