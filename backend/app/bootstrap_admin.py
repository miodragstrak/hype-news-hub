"""Owner-only initial administrator creation; no password arguments or default account."""
import getpass
import sys

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.session import create_database_engine
from app.models.auth import User
from app.services.authentication import USER_LOCK, email_address, password_hash
from app.services.security_events import record_user_event


def bootstrap_admin(config, email, password):
    normalized, encoded = email_address(email), password_hash(password)
    engine = create_database_engine(config)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"), {"key": USER_LOCK})
            with Session(bind=connection) as session:
                if session.scalar(select(func.count()).select_from(User)):
                    raise ValueError("Bootstrap refused: accounts already exist. Use authenticated administration.")
                user = User(email=normalized, password_hash=encoded, role="admin", active=True, revision=1)
                session.add(user)
                session.flush()
                record_user_event(session, None, user, "user.created")
                session.flush()
    finally:
        engine.dispose()


def interactive_bootstrap(config):
    if not sys.stdin.isatty():
        raise ValueError("Bootstrap requires an interactive terminal; passwords must not be passed as arguments.")
    email = input("Initial administrator email: ")
    password = getpass.getpass("Password (15–128 characters): ")
    if getpass.getpass("Confirm password: ") != password:
        raise ValueError("Passwords do not match.")
    bootstrap_admin(config, email, password)
    print("Initial administrator created. No session was issued.")
