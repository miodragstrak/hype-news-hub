"""Append-only, attributable account-security events. Forward-only."""
from alembic import op
import sqlalchemy as sa

revision = "20261104_08"
down_revision = "20261104_07"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("app_security_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("public.app_users.id", ondelete="RESTRICT")),
        sa.Column("actor_issuer", sa.String(128), nullable=False),
        sa.Column("actor_subject", sa.String(128), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), sa.ForeignKey("public.app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("previous_role", sa.String(16)),
        sa.Column("new_role", sa.String(16), nullable=False),
        sa.Column("previous_active", sa.Boolean()),
        sa.Column("new_active", sa.Boolean(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("action IN ('user.created', 'user.activated', 'user.deactivated', 'user.role_changed', 'user.updated', 'user.update_rejected', 'user.create_rejected')", name=op.f("ck_app_security_events_action")),
        sa.CheckConstraint("outcome IN ('success', 'conflict', 'denied')", name=op.f("ck_app_security_events_outcome")),
        sa.CheckConstraint("previous_role IS NULL OR previous_role IN ('admin', 'editor')", name=op.f("ck_app_security_events_previous_role")),
        sa.CheckConstraint("new_role IN ('admin', 'editor')", name=op.f("ck_app_security_events_new_role")),
        sa.CheckConstraint("target_revision > 0", name=op.f("ck_app_security_events_target_revision")), schema="public")
    op.create_index("ix_app_security_events_target_user_id", "app_security_events", ["target_user_id"], schema="public")
    op.create_index("ix_app_security_events_occurred_at", "app_security_events", ["occurred_at"], schema="public")
    op.execute("""CREATE FUNCTION public.hwn_security_event_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN RAISE EXCEPTION 'Account-security history is immutable' USING ERRCODE='23514'; END $$""")
    op.execute("REVOKE ALL ON FUNCTION public.hwn_security_event_immutable() FROM PUBLIC")
    op.execute("""CREATE TRIGGER app_security_events_immutable BEFORE UPDATE OR DELETE
        ON public.app_security_events FOR EACH ROW EXECUTE FUNCTION public.hwn_security_event_immutable()""")


def downgrade():
    raise RuntimeError("Account-security history migration is forward-only. Restore a reviewed backup into a separate database.")
