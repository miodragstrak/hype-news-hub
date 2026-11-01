from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings

TRUSTED_SEARCH_PATH = "public, pg_catalog, pg_temp"


def _restore_search_path(dbapi_connection, *_):
    # Pool rollback does not reset a committed SET SESSION. Set outside a
    # transaction so a later rollback cannot resurrect the previous path.
    previous = dbapi_connection.autocommit
    try:
        dbapi_connection.autocommit = True
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET SESSION search_path TO " + TRUSTED_SEARCH_PATH)
    finally:
        dbapi_connection.autocommit = previous


def create_database_engine(config: Settings) -> Engine:
    engine = create_engine(
        config.database_url, pool_pre_ping=True,
        pool_size=config.database_pool_size, max_overflow=config.database_max_overflow,
        pool_timeout=config.database_pool_timeout_seconds, pool_recycle=1800,
        hide_parameters=True,
        # Startup options also protect dialect initialization from role/database defaults.
        connect_args={"options": "-csearch_path=" + TRUSTED_SEARCH_PATH.replace(" ", "")},
    )
    event.listen(engine, "checkout", _restore_search_path)
    return engine


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
