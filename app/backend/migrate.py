"""Bring the database to the latest schema. Runs before the API starts (see Dockerfile).

1. A database created before Alembic (tables in public, no alembic_version) is stamped
   at the baseline revision 0001 instead of re-creating its tables.
2. `alembic upgrade head`.
3. Grant each module role access to its own schema only (DESIGN.md §6.1). Roles are
   created once by a database admin (db/roles.sql); missing roles are skipped, and the
   grants are re-applied on every start so roles added later get their privileges.
"""
import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")
log.setLevel(logging.INFO)  # alembic.ini's logging config sets the root logger to WARNING

HERE = Path(__file__).resolve().parent
BASELINE_TABLES = {"users", "monitors", "monitor_checks", "contact_submissions", "blog_posts", "services", "page_visits"}
SCHEMA_ROLES = {"core": "core_svc", "uptime": "uptime_svc", "site": "site_svc"}
MIGRATION_LOCK = 724100  # arbitrary pg_advisory_lock key


def migration_url() -> str:
    url = os.getenv("DATABASE_MIGRATION_URL") or os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    return url


def stamp_legacy_database(conn, cfg: Config) -> None:
    insp = inspect(conn)
    if insp.has_table("alembic_version"):
        return
    legacy = set(insp.get_table_names(schema="public")) & BASELINE_TABLES
    if not legacy:
        return  # empty database: migrations create everything
    missing = BASELINE_TABLES - legacy
    if missing:
        sys.exit(f"Pre-Alembic database is missing {sorted(missing)}; refusing to stamp it as baseline")
    log.info("Existing pre-Alembic database found; stamping baseline 0001")
    command.stamp(cfg, "0001")


def apply_grants(conn) -> None:
    for schema, role in SCHEMA_ROLES.items():
        if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
            continue
        for stmt in (
            f"GRANT USAGE ON SCHEMA {schema} TO {role}",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {role}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {role}",
        ):
            conn.execute(text(stmt))
        log.info("Granted %s access to schema %s", role, schema)


def main() -> None:
    engine = create_engine(migration_url())
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE / "migrations"))

    with engine.connect() as conn:
        # Serialise concurrent starts (e.g. API and worker containers)
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK})
        try:
            cfg.attributes["connection"] = conn
            stamp_legacy_database(conn, cfg)
            conn.commit()
            command.upgrade(cfg, "head")
            conn.commit()
            apply_grants(conn)
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK})
            conn.commit()
    log.info("Database is at head")


if __name__ == "__main__":
    main()
