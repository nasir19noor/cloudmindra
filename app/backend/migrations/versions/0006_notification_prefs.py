"""Per-member email alert preferences (DESIGN.md §4.1, §7). No row = alert on.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_prefs",
        sa.Column("membership_id", sa.Integer(), sa.ForeignKey("core.memberships.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_key", sa.String(60), primary_key=True),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("notification_prefs", schema="core")
