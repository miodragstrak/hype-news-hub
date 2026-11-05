"""Authentication data is separate from immutable editorial history."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, MetaData, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKey


class AuthBase(DeclarativeBase):
    metadata = MetaData(schema="public", naming_convention=Base.metadata.naming_convention)


class User(UUIDPrimaryKey, AuthBase):
    __tablename__ = "app_users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'editor')", name="role"),
                     CheckConstraint("email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254", name="email"),
                     CheckConstraint("revision > 0", name="revision"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(AuthBase):
    __tablename__ = "app_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("public.app_users.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginThrottle(AuthBase):
    __tablename__ = "app_login_throttles"
    __table_args__ = (CheckConstraint("bucket BETWEEN 0 AND 8192", name="bounded_bucket"),)
    bucket: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)


class SecurityEvent(UUIDPrimaryKey, AuthBase):
    """Append-only account events. No arbitrary request data or credential fields."""
    __tablename__ = "app_security_events"
    __table_args__ = (
        CheckConstraint("action IN ('user.created', 'user.activated', 'user.deactivated', 'user.role_changed', 'user.updated', 'user.update_rejected', 'user.create_rejected')", name="action"),
        CheckConstraint("outcome IN ('success', 'conflict', 'denied')", name="outcome"),
        CheckConstraint("previous_role IS NULL OR previous_role IN ('admin', 'editor')", name="previous_role"),
        CheckConstraint("new_role IN ('admin', 'editor')", name="new_role"),
        CheckConstraint("target_revision > 0", name="target_revision"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("public.app_users.id", ondelete="RESTRICT"))
    actor_issuer: Mapped[str] = mapped_column(String(128))
    actor_subject: Mapped[str] = mapped_column(String(128))
    target_user_id: Mapped[UUID] = mapped_column(ForeignKey("public.app_users.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), index=True)
    previous_role: Mapped[str | None] = mapped_column(String(16))
    new_role: Mapped[str] = mapped_column(String(16))
    previous_active: Mapped[bool | None] = mapped_column(Boolean)
    new_active: Mapped[bool] = mapped_column(Boolean)
    target_revision: Mapped[int] = mapped_column(Integer)
