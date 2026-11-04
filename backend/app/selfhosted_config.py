"""Secrets and migration-marker policy for opt-in self-hosted entry points only."""
import os
from pathlib import Path


def load_database_secrets(*, provisioning: bool = False) -> None:
    names = ["POSTGRES_PASSWORD"]
    if provisioning:
        names.append("POSTGRES_RUNTIME_PASSWORD")
    for name in names:
        filename = os.environ.get(name + "_FILE")
        if not filename or os.environ.get(name):
            raise ValueError("Self-hosted database secrets require file-only configuration.")
        try:
            with Path(filename).open("rb") as handle:
                raw = handle.read(4097)
            value = raw.decode("utf-8").rstrip("\n")
            if len(raw) > 4096 or not value or "\x00" in value:
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise ValueError("Self-hosted database secret is missing, unreadable or invalid.") from None
        os.environ[name] = value


def assert_migration_marker_permissions(connection, role: str | None = None) -> None:
    from sqlalchemy import text
    from app.database.runtime_security import COLUMN_PRIVILEGES, TABLE_PRIVILEGES
    role = role or connection.execute(text("SELECT current_user")).scalar_one()
    for function, privileges in (("has_table_privilege", TABLE_PRIVILEGES),
                                 ("has_any_column_privilege", COLUMN_PRIVILEGES)):
        for privilege in privileges:
            checks = ([privilege] if privilege != "SELECT" else []) + [privilege + " WITH GRANT OPTION"]
            for checked in checks:
                if connection.execute(text(f"SELECT pg_catalog.{function}(CAST(:role AS pg_catalog.name), "
                                           "'public.alembic_version', :privilege)"),
                                      {"role": role, "privilege": checked}).scalar_one():
                    raise ValueError("Migration marker permissions require administrator review; shared grants were not changed.")
