"""Tiers per module: core.org_apps and core.usage_counters (DESIGN.md §5).

A workspace without an org_apps row for a module is on Free with catalog limits,
so no backfill is needed for existing or future workspaces and modules.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "org_apps",
        sa.Column("org_id", sa.String(), sa.ForeignKey("core.organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("app_key", sa.String(20), primary_key=True),
        sa.Column("tier", sa.String(10), nullable=False, server_default="free"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("limits", JSONB()),
        sa.Column("pro_since", TZ),
        sa.Column("pro_until", TZ),
        sa.Column("updated_by", sa.String()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, server_default=sa.func.now()),
        sa.CheckConstraint("tier IN ('free', 'pro')", name="ck_org_apps_tier"),
        sa.CheckConstraint("status IN ('active', 'trial', 'past_due', 'cancelled')", name="ck_org_apps_status"),
        schema="core",
    )
    op.create_table(
        "usage_counters",
        sa.Column("org_id", sa.String(), sa.ForeignKey("core.organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("metric", sa.String(50), primary_key=True),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("usage_counters", schema="core")
    op.drop_table("org_apps", schema="core")
