"""Explicit, owner-only commands. Never run migrations from the API startup."""
import os
import sys

from app.selfhosted_config import assert_migration_marker_permissions, load_database_secrets


def provision_selfhosted_role(config, role, password):
    from sqlalchemy import text
    from app.database.runtime_security import provision_runtime_role
    from app.database.session import create_database_engine
    provision_runtime_role(config, role, password)
    engine = create_database_engine(config)
    try:
        with engine.begin() as connection:
            quoted = engine.dialect.identifier_preparer.quote(role)
            connection.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM {quoted} RESTRICT"))
            connection.execute(text(f"REVOKE ALL PRIVILEGES (version_num) ON TABLE public.alembic_version FROM {quoted} RESTRICT"))
            connection.execute(text(f"GRANT SELECT (version_num) ON TABLE public.alembic_version TO {quoted}"))
            assert_migration_marker_permissions(connection, role)
    finally:
        engine.dispose()


def main():
    action = sys.argv[1:]
    if not action or action[0] not in {"migrate", "provision"}:
        raise SystemExit("Usage: selfhosted_tools migrate <alembic arguments> | provision")
    load_database_secrets(provisioning=action[0] == "provision")
    if action[0] == "migrate":
        from alembic.config import main as alembic_main
        alembic_main(argv=action[1:])
    else:
        from app.core.config import Settings
        provision_selfhosted_role(Settings(_env_file=None), os.environ["POSTGRES_RUNTIME_USER"],
                                 os.environ["POSTGRES_RUNTIME_PASSWORD"])
        print("Restricted runtime role provisioned.")


if __name__ == "__main__":
    main()
