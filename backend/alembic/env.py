from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.database.base import Base
from app import models  # Register all mapped tables in Base.metadata.

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata,
        compare_type=True, compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Integration tests can supply an existing connection without putting a
    # password-bearing URL through ConfigParser interpolation or logging.
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        migrate_connection(supplied_connection)
        return
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with connectable.connect() as connection:
            migrate_connection(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
