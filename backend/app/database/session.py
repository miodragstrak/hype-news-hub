from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings


def create_database_engine(config: Settings) -> Engine:
    return create_engine(
        config.database_url, pool_pre_ping=True,
        pool_size=config.database_pool_size, max_overflow=config.database_max_overflow,
        pool_timeout=config.database_pool_timeout_seconds, pool_recycle=1800,
        hide_parameters=True,
    )


@lru_cache
def get_engine() -> Engine:
    # No engine, connection, or credentials are needed merely to import the API.
    return create_database_engine(settings)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """An explicit unit of work: commit on success, rollback on error, always close."""
    with (factory or create_session_factory(get_engine())).begin() as session:
        yield session


def get_db() -> Iterator[Session]:
    """Future FastAPI dependency. Callers own commit/transaction boundaries."""
    with create_session_factory(get_engine())() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
