"""Explicit, owner-only commands. Never run migrations from the API startup."""
import os
import sys

from app.selfhosted_config import assert_migration_marker_permissions, load_database_secrets


def provision_selfhosted_role(config, role, password):
    from sqlalchemy import text
    from app.database.runtime_security import provision_runtime_role
    from app.database.session import create_database_engine
    # Authentication grants exist only in the self-hosted role, after revision 07.
    from app.services.authentication import AUTH_POLICY
    provision_runtime_role(config, role, password, policy=AUTH_POLICY)
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
    if not action or action[0] not in {"migrate", "provision", "bootstrap-admin"}:
        raise SystemExit("Usage: selfhosted_tools migrate <alembic arguments> | provision | bootstrap-admin")
    if action[0] != "migrate" and len(action) != 1:
        raise SystemExit("This command takes no arguments or passwords.")
    load_database_secrets(provisioning=action[0] == "provision")
    if action[0] == "migrate":
        from alembic.config import main as alembic_main
        alembic_main(argv=action[1:])
    elif action[0] == "provision":
        from app.core.config import Settings
        provision_selfhosted_role(Settings(_env_file=None), os.environ["POSTGRES_RUNTIME_USER"],
                                 os.environ["POSTGRES_RUNTIME_PASSWORD"])
        print("Restricted runtime role provisioned.")
    else:
        from app.core.config import Settings
        from app.bootstrap_admin import interactive_bootstrap
        interactive_bootstrap(Settings(_env_file=None))


if __name__ == "__main__":
    main()
