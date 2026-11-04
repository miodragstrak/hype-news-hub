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
