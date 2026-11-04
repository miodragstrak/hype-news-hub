"""Application users, hashed opaque sessions and bounded distributed login throttles."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_07"
down_revision = "20261101_06"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("app_users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("email", name=op.f("uq_app_users_email")),
        sa.CheckConstraint("role IN ('admin', 'editor')", name=op.f("ck_app_users_role")),
        sa.CheckConstraint("email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254", name=op.f("ck_app_users_email")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_app_users_revision")), schema="public")
    op.create_table("app_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("public.app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), schema="public")
    op.create_index("ix_app_sessions_user_id", "app_sessions", ["user_id"], schema="public")
    op.create_index("ix_app_sessions_expires_at", "app_sessions", ["expires_at"], schema="public")
    op.create_table("app_login_throttles",
        sa.Column("bucket", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("bucket BETWEEN 0 AND 8192", name=op.f("ck_app_login_throttles_bounded_bucket")), schema="public")


def downgrade():
    raise RuntimeError("Application authentication migration is forward-only. Restore a reviewed backup into a separate database.")
