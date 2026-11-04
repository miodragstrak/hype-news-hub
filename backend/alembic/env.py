from logging.config import fileConfig
from contextlib import nullcontext

from alembic import context
from sqlalchemy import MetaData, create_engine, pool
from sqlalchemy.schema import BLANK_SCHEMA

from app.core.config import settings
from app.database.base import Base
from app.database.session import TRUSTED_SEARCH_PATH
from app import models  # Register all mapped tables in Base.metadata.
from app.models.auth import AuthBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Revisions 01/02/03 describe the existing public schema without explicit schema
# arguments. Normalize only Alembic's comparison copy to that representation;
# runtime models stay qualified and no historical revision needs rewriting.
target_metadata = MetaData(naming_convention=Base.metadata.naming_convention)
comparison_tables = list(Base.metadata.sorted_tables)
if not config.attributes.get("legacy_editorial_schema_only", False):
    comparison_tables += list(AuthBase.metadata.sorted_tables)
for table in comparison_tables:
    if table.schema != "public":
        raise ValueError("Application migrations require an explicitly reviewed trusted-schema policy.")
    table.to_metadata(target_metadata, schema=None,
        referred_schema_fn=lambda table, schema, constraint, referred: BLANK_SCHEMA if referred == "public" else referred)


def include_object(obj, name, type_, reflected, compare_to):
    # The explicit version-table schema and the dialect's default public schema
    # are the same physical namespace; Alembic 1.16 otherwise compares its own table.
    return not (type_ == "table" and name == "alembic_version" and obj.schema in (None, "public"))


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        version_table_schema="public",
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection) -> None:
    # Migrations remain owner-only tools. Pin legacy unqualified DDL/data SQL,
    # including supplied test connections, without committing a caller's transaction.
    with nullcontext() if connection.in_transaction() else connection.begin():
        connection.exec_driver_sql("SET LOCAL search_path TO " + TRUSTED_SEARCH_PATH)
        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True, compare_server_default=True, version_table_schema="public",
            include_object=include_object,
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
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool, hide_parameters=True,
        connect_args={"options": "-csearch_path=" + TRUSTED_SEARCH_PATH.replace(" ", "")})
    try:
        with connectable.connect() as connection:
            migrate_connection(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
