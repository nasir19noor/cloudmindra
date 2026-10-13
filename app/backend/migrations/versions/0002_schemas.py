"""Schemas per module: move tables out of public (DESIGN.md §6.1).

core   ← users
uptime ← monitors, monitor_checks (renamed to checks)
site   ← contact_submissions, blog_posts, services, page_visits

The monitors.user_id → users foreign key would cross schemas, so it is dropped.
ALTER TABLE … SET SCHEMA also moves the table's indexes, constraints and owned sequences.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MOVES = {
    "core": ["users"],
    "uptime": ["monitors", "monitor_checks"],
    "site": ["contact_submissions", "blog_posts", "services", "page_visits"],
}


def _drop_foreign_keys(table: str) -> None:
    op.execute(f"""
        DO $$
        DECLARE c record;
        BEGIN
          FOR c IN SELECT conname FROM pg_constraint
                   WHERE conrelid = '{table}'::regclass AND contype = 'f' LOOP
            EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', c.conname);
          END LOOP;
        END $$;
    """)


def upgrade() -> None:
    for schema in MOVES:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Must go before the move: it is the only FK that would point across schemas
    _drop_foreign_keys("public.monitors")

    for schema, tables in MOVES.items():
        for table in tables:
            op.execute(f"ALTER TABLE public.{table} SET SCHEMA {schema}")

    op.execute("ALTER TABLE uptime.monitor_checks RENAME TO checks")
    op.execute("ALTER INDEX uptime.ix_monitor_checks_monitor_id RENAME TO ix_checks_monitor_id")
    op.execute("ALTER INDEX uptime.ix_monitor_checks_checked_at RENAME TO ix_checks_checked_at")


def downgrade() -> None:
    op.execute("ALTER INDEX uptime.ix_checks_checked_at RENAME TO ix_monitor_checks_checked_at")
    op.execute("ALTER INDEX uptime.ix_checks_monitor_id RENAME TO ix_monitor_checks_monitor_id")
    op.execute("ALTER TABLE uptime.checks RENAME TO monitor_checks")
    for schema, tables in MOVES.items():
        for table in tables:
            op.execute(f"ALTER TABLE {schema}.{table} SET SCHEMA public")
    op.execute("""
        ALTER TABLE public.monitors ADD CONSTRAINT monitors_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES public.users (id) ON DELETE CASCADE NOT VALID
    """)
    for schema in MOVES:
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
