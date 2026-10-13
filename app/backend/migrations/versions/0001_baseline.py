"""Baseline: the schema created by the pre-Alembic create_all (everything in public).

Production already has these tables; migrate.py stamps it at this revision instead
of running it. Fresh databases run it normally.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "contact_submissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("status", sa.String()),
    )
    op.create_table(
        "blog_posts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.String()),
        sa.Column("author", sa.String()),
        sa.Column("published", sa.Boolean()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("updated_at", TZ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String()),
        sa.Column("provider", sa.String(50)),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("last_login_at", TZ),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table(
        "services",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String()),
        sa.Column("order", sa.Integer()),
    )
    op.create_table(
        "page_visits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("visitor_ip", sa.String(45)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("os", sa.String(50)),
        sa.Column("device_type", sa.String(20)),
        sa.Column("browser", sa.String(50)),
        sa.Column("country", sa.String(100)),
        sa.Column("city", sa.String(100)),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("path", sa.String(500)),
        sa.Column("referrer", sa.Text()),
        sa.Column("visited_at", TZ, server_default=sa.func.now()),
    )
    op.create_index("ix_page_visits_visitor_ip", "page_visits", ["visitor_ip"])
    op.create_index("ix_page_visits_path", "page_visits", ["path"])
    op.create_index("ix_page_visits_visited_at", "page_visits", ["visited_at"])
    op.create_table(
        "monitors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("down_since", TZ),
        sa.Column("last_checked_at", TZ),
        sa.Column("last_status_code", sa.Integer()),
        sa.Column("last_response_ms", sa.Integer()),
        sa.Column("last_error", sa.String(300)),
        sa.Column("ssl_expires_at", TZ),
        sa.Column("ssl_checked_at", TZ),
        sa.Column("ssl_alerted_for", TZ),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
    )
    op.create_index("ix_monitors_user_id", "monitors", ["user_id"])
    op.create_table(
        "monitor_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("monitor_id", sa.String(), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_at", TZ, nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("response_ms", sa.Integer()),
        sa.Column("error", sa.String(300)),
    )
    op.create_index("ix_monitor_checks_monitor_id", "monitor_checks", ["monitor_id"])
    op.create_index("ix_monitor_checks_checked_at", "monitor_checks", ["checked_at"])


def downgrade() -> None:
    for table in ("monitor_checks", "monitors", "page_visits", "services", "users", "blog_posts", "contact_submissions"):
        op.drop_table(table)
