"""PostgreSQL sessions; all credentials and editorial roles are resolved server-side."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
from threading import BoundedSemaphore

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.editorial_security import EditorialPrincipal, EditorialRole, InvalidEditorialIdentity
from app.database.runtime_security import RUNTIME_PRIVILEGE_ALLOWLIST, assert_runtime_role
from app.models.auth import User, LoginSession, LoginThrottle
from app.repositories.news_repository import StorageUnavailable
from app.services.security_events import record_user_event

AUTH_PRIVILEGES = {name: ("SELECT", "INSERT", "UPDATE") for name in
                   ("app_users", "app_sessions", "app_login_throttles")}
AUTH_POLICY = RUNTIME_PRIVILEGE_ALLOWLIST | AUTH_PRIVILEGES | {"app_security_events": ("SELECT", "INSERT")}
USER_LOCK = 724913802113
THROTTLE_LOCK = 724913802114
COOKIE = "__Host-hwn_session"
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
HASH_BUDGET = BoundedSemaphore(2)


class AuthError(Exception):
    def __init__(self, status=401, detail="Authentication failed."):
        self.status, self.detail = status, detail


def email_address(value):
    value = value.strip().lower()
    if len(value) > 254 or not value.isascii() or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError("Invalid account data.")
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split(".")):
        raise ValueError("Invalid account data.")
    return value


def password_hash(value):
    if not 15 <= len(value) <= 128 or "\x00" in value:
        raise ValueError("Password must contain 15–128 characters.")
    value.encode("utf8")
    with HASH_BUDGET:
        return HASHER.hash(value)


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def csrf_token(value):
    return hmac.new(value.encode("ascii"), b"hwn-csrf-v1", hashlib.sha256).hexdigest()


def user_read(user):
    return {name: getattr(user, name) for name in ("id", "email", "role", "active", "revision", "created_at", "last_login_at")}


@dataclass(frozen=True)
class AuthenticatedSession:
    token_hash: str
    csrf: str
    account: dict
    principal: EditorialPrincipal


class Authentication:
    def __init__(self, repository):
        self.repository = repository

    @contextmanager
    def transaction(self):
        try:
            with self.repository.engine.connect() as connection, connection.begin():
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                assert_runtime_role(connection, policy=AUTH_POLICY)
                with Session(bind=connection, expire_on_commit=False) as session:
                    yield session
                    session.flush()
        except (SQLAlchemyError, ValueError):
            raise StorageUnavailable() from None

    def resolve_in_session(self, session, token_hash):
        row = session.execute(select(LoginSession, User).join(User, User.id == LoginSession.user_id)
            .where(LoginSession.token_hash == token_hash, LoginSession.revoked_at.is_(None),
                   LoginSession.expires_at > func.pg_catalog.clock_timestamp(), User.active.is_(True))).first()
        if row is None:
            raise AuthError()
        return row

    def resolve(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AuthError()
        with self.transaction() as session:
            _, user = self.resolve_in_session(session, digest(token))
            role = EditorialRole.ADMINISTRATOR if user.role == "admin" else EditorialRole.EDITOR
            return AuthenticatedSession(digest(token), csrf_token(token), user_read(user),
                EditorialPrincipal("urn:hype-world-news:accounts", str(user.id), frozenset({role})))

    def throttle(self, email, address):
        # Fixed bucket space prevents unbounded storage growth from invented emails/IPs.
        bucket = lambda value: int(hashlib.sha256(value.encode()).hexdigest(), 16) % 4096
        entries = [(1 + bucket(address), 10), (4097 + bucket(email), 5), (0, 30)]
        limited = False
        with self.transaction() as session:
            session.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"), {"key": THROTTLE_LOCK})
            now = session.scalar(select(func.pg_catalog.clock_timestamp()))
            rows = []
            for key, limit in entries:
                row = session.get(LoginThrottle, key)
                if row is None:
                    row = LoginThrottle(bucket=key, started_at=now, attempts=0)
                    session.add(row)
                if (now - row.started_at).total_seconds() >= 60:
                    row.started_at, row.attempts = now, 0
                rows.append(row)
                if row.attempts >= limit:
                    limited = True
                    break
            # Admit and charge all budgets atomically, or charge none. Already
            # blocked IPs/accounts cannot spend unrelated global login capacity.
            if not limited:
                for row in rows:
                    row.attempts += 1
        if limited:
            raise AuthError(429, "Unable to sign in. Try again later.")

    def login(self, email, password, address):
        normalized = email.strip().lower()[:254]
        self.throttle(normalized, address)
        try:
            normalized = email_address(email)
        except ValueError:
            normalized = ""
        with self.transaction() as session:
            user = session.scalar(select(User).where(User.email == normalized))
            candidate = user.password_hash if user else DUMMY_HASH
            user_id = user.id if user else None
        try:
            with HASH_BUDGET:
                valid = HASHER.verify(candidate, password)
        except (VerificationError, InvalidHashError, ValueError, UnicodeError):
            valid = False
        if not valid or user_id is None:
            raise AuthError()
        # Hashing is outside DB transactions. Recheck active/hash after verification.
        with self.transaction() as session:
            user = session.get(User, user_id, with_for_update=True)
            if not user.active or user.password_hash != candidate:
                raise AuthError()
            now = session.scalar(select(func.pg_catalog.clock_timestamp()))
            token = secrets.token_urlsafe(32)
            session.add(LoginSession(token_hash=digest(token), user_id=user.id, created_at=now,
                expires_at=now + timedelta(seconds=self.repository.config.auth_session_seconds)))
            user.last_login_at = now
        return token

    def logout(self, context):
        with self.transaction() as session:
            session.execute(update(LoginSession).where(LoginSession.token_hash == context.token_hash,
                LoginSession.revoked_at.is_(None)).values(revoked_at=func.pg_catalog.clock_timestamp()))

    def admin(self, session, context):
        session.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"), {"key": USER_LOCK})
        _, actor = self.resolve_in_session(session, context.token_hash)
        if actor.role != "admin":
            raise AuthError(403, "Permission denied.")
        return actor

    def users(self, context, limit, offset):
        with self.transaction() as session:
            self.admin(session, context)
            return [user_read(u) for u in session.scalars(select(User).order_by(User.email).limit(limit).offset(offset))]

    def create_user(self, context, email, password, role):
        try:
            normalized, encoded = email_address(email), password_hash(password)
        except (ValueError, UnicodeError):
            raise AuthError(422, "Invalid account data.") from None
        error = None
        with self.transaction() as session:
            actor = self.admin(session, context)
            existing = session.scalar(select(User).where(User.email == normalized))
            if existing:
                record_user_event(session, actor, existing, "user.create_rejected", "conflict", (existing.role, existing.active))
                error = AuthError(409, "Unable to create account.")
            else:
                user = User(email=normalized, password_hash=encoded, role=role, active=True, revision=1)
                session.add(user)
                session.flush()
                record_user_event(session, actor, user, "user.created")
                result = user_read(user)
        if error:
            raise error
        return result

    def update_user(self, context, user_id, revision, role, active):
        error = None
        with self.transaction() as session:
            actor = self.admin(session, context)
            user = session.get(User, user_id, with_for_update=True)
            if user is None:
                raise AuthError(404, "Account not found.")
            previous = (user.role, user.active)
            if user.revision != revision:
                error = AuthError(409, "Account changed. Reload before saving.")
            elif user.active and user.role == "admin" and (not active or role != "admin"):
                admins = session.scalar(select(func.count()).select_from(User).where(User.active.is_(True), User.role == "admin"))
                if admins <= 1:
                    error = AuthError(409, "A replacement active administrator is required.")
            if error:
                record_user_event(session, actor, user, "user.update_rejected", "conflict", previous)
            else:
                user.role, user.active, user.revision = role, active, user.revision + 1
                if not active:
                    session.execute(update(LoginSession).where(LoginSession.user_id == user.id,
                        LoginSession.revoked_at.is_(None)).values(revoked_at=func.pg_catalog.clock_timestamp()))
                actions = []
                if previous[0] != role:
                    actions.append("user.role_changed")
                if previous[1] != active:
                    actions.append("user.activated" if active else "user.deactivated")
                for action in actions or ["user.updated"]:
                    record_user_event(session, actor, user, action, previous=previous)
                session.flush()
                result = user_read(user)
        # A rejected administrative action persists its event, but no account edit.
        if error:
            raise error
        return result


class SessionIdentityVerifier:
    def __init__(self, service):
        self.service = service

    def resolve(self, token):
        return self.service.resolve(token)

    async def verify(self, token):
        from starlette.concurrency import run_in_threadpool
        try:
            return (await run_in_threadpool(self.resolve, token)).principal
        except AuthError:
            raise InvalidEditorialIdentity() from None
