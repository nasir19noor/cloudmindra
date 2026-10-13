"""Workspaces: organizations, memberships, invitations; monitors belong to a workspace.

Every existing user gets a personal workspace ("{name}'s workspace") with themselves as
owner, and their monitors move into it. monitors.user_id becomes created_by.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def personal_workspace_name(name: str | None, email: str) -> str:
    # Kept in sync with orgs.personal_workspace_name (migrations must not import app code)
    owner = (name or "").strip() or email.split("@")[0]
    return f"{owner}'s workspace"[:100]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("member_limit", sa.Integer()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("core.users.id", ondelete="SET NULL")),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, server_default=sa.func.now()),
        schema="core",
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("core.organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("core.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="ck_memberships_role"),
        schema="core",
    )
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"], schema="core")
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], schema="core")
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("core.organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(), sa.ForeignKey("core.users.id", ondelete="SET NULL")),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("accepted_at", TZ),
        sa.Column("created_at", TZ, server_default=sa.func.now()),
        schema="core",
    )
    op.create_index("ix_invitations_org_id", "invitations", ["org_id"], schema="core")

    op.add_column("users", sa.Column("last_org_id", sa.String()), schema="core")

    # Monitors: user_id -> created_by (nullable, no FK) + org_id
    op.alter_column("monitors", "user_id", new_column_name="created_by", nullable=True, schema="uptime")
    op.execute("ALTER INDEX uptime.ix_monitors_user_id RENAME TO ix_monitors_created_by")
    op.add_column("monitors", sa.Column("org_id", sa.String()), schema="uptime")

    # Backfill a personal workspace for every existing user
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, name, email FROM core.users")).all()
    for user_id, name, email in users:
        org_id = str(uuid.uuid4())
        conn.execute(
            sa.text("INSERT INTO core.organizations (id, name, created_by) VALUES (:id, :name, :uid)"),
            {"id": org_id, "name": personal_workspace_name(name, email), "uid": user_id},
        )
        conn.execute(
            sa.text("INSERT INTO core.memberships (org_id, user_id, role) VALUES (:org, :uid, 'owner')"),
            {"org": org_id, "uid": user_id},
        )
        conn.execute(sa.text("UPDATE core.users SET last_org_id = :org WHERE id = :uid"), {"org": org_id, "uid": user_id})
        conn.execute(sa.text("UPDATE uptime.monitors SET org_id = :org WHERE created_by = :uid"), {"org": org_id, "uid": user_id})

    # The old FK cascaded on user delete, so orphans should not exist; drop any defensively
    op.execute("DELETE FROM uptime.monitors WHERE org_id IS NULL")
    op.alter_column("monitors", "org_id", nullable=False, schema="uptime")
    op.create_index("ix_monitors_org_id", "monitors", ["org_id"], schema="uptime")


def downgrade() -> None:
    op.drop_index("ix_monitors_org_id", table_name="monitors", schema="uptime")
    op.drop_column("monitors", "org_id", schema="uptime")
    op.execute("DELETE FROM uptime.monitors WHERE created_by IS NULL")
    op.execute("ALTER INDEX uptime.ix_monitors_created_by RENAME TO ix_monitors_user_id")
    op.alter_column("monitors", "created_by", new_column_name="user_id", nullable=False, schema="uptime")
    op.drop_column("users", "last_org_id", schema="core")
    op.drop_table("invitations", schema="core")
    op.drop_table("memberships", schema="core")
    op.drop_table("organizations", schema="core")
