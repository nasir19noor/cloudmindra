"""Platform services: jobs, schedules, audit log, and an outbox in core and uptime (DESIGN.md §6.1, §7).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _outbox(schema: str) -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("org_id", sa.String()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", TZ),
        schema=schema,
    )
    for col in ("org_id", "created_at", "published_at"):
        op.create_index(f"ix_outbox_{col}", "outbox", [col], schema=schema)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String()),
        sa.Column("app_key", sa.String(20), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("dedupe_key", sa.String(200), unique=True),
        sa.Column("run_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_by", sa.String(100)),
        sa.Column("locked_at", TZ),
        sa.Column("result", JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.String()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("finished_at", TZ),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="ck_jobs_status"),
        schema="core",
    )
    op.create_index("ix_jobs_org_id", "jobs", ["org_id"], schema="core")
    op.create_index("ix_jobs_status_run_at", "jobs", ["status", "run_at"], schema="core")

    op.create_table(
        "schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String()),
        sa.Column("app_key", sa.String(20), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", TZ, nullable=False),
        sa.Column("last_run_at", TZ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        schema="core",
    )
    op.create_index("ix_schedules_org_id", "schedules", ["org_id"], schema="core")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String()),
        sa.Column("actor_user_id", sa.String()),
        sa.Column("actor_email", sa.String()),
        sa.Column("app_key", sa.String(20)),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_id", sa.String()),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("ip", sa.String(45)),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        schema="core",
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"], schema="core")
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], schema="core")

    _outbox("core")
    _outbox("uptime")


def downgrade() -> None:
    op.drop_table("outbox", schema="uptime")
    op.drop_table("outbox", schema="core")
    op.drop_table("audit_events", schema="core")
    op.drop_table("schedules", schema="core")
    op.drop_table("jobs", schema="core")
