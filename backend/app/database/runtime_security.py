"""Runtime checks and explicit, operator-invoked least-privilege provisioning."""
import os
import re

from sqlalchemy import text

from app.core.config import Settings
from app.database.session import create_database_engine

RUNTIME_TABLES = (
    "news_sources", "collected_articles", "article_identities", "stories",
    "story_articles", "collection_runs", "collection_source_results",
)


def assert_runtime_role(connection) -> None:
    unsafe = connection.execute(text("""SELECT
        EXISTS (SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user, r.oid, 'MEMBER')
            AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls))
        OR has_schema_privilege(current_user, 'public', 'CREATE')
        OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND pg_has_role(current_user, c.relowner, 'MEMBER'))
    """)).scalar_one()
    if unsafe:
        raise ValueError("PostgreSQL mode requires a restricted runtime role, separate from the schema owner.")


def provision_runtime_role(config: Settings, role: str, password: str) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role) or role.startswith("pg_") or role == config.postgres_user:
        raise ValueError("Choose a separate, non-system PostgreSQL runtime role name.")
    if len(password) < 24:
        raise ValueError("POSTGRES_RUNTIME_PASSWORD must contain at least 24 characters.")
    engine = create_database_engine(config)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT set_config('hnh.runtime_role', :role, true), set_config('hnh.runtime_password', :password, true)"), {"role": role, "password": password})
            # Passwords are bound parameters above, never interpolated into SQL logs.
            connection.execute(text("""DO $$ DECLARE runtime_name text := current_setting('hnh.runtime_role');
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_name) THEN
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_name
                            AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
                            OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = runtime_name)
                            OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner WHERE r.rolname = runtime_name)
                            OR EXISTS (SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner WHERE r.rolname = runtime_name)
                            OR EXISTS (SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba WHERE r.rolname = runtime_name)
                        THEN RAISE EXCEPTION 'Refusing to repurpose a privileged or owning role'; END IF;
                    ELSE
                        EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', runtime_name);
                    END IF;
                    EXECUTE format('ALTER ROLE %I PASSWORD %L', runtime_name, current_setting('hnh.runtime_password'));
                    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), runtime_name);
                    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', runtime_name);
                    EXECUTE format('GRANT EXECUTE ON FUNCTION public.hnh_identity_hash(text) TO %I', runtime_name);
                END $$"""))
            quoted = engine.dialect.identifier_preparer.quote(role)
            tables = ", ".join("public." + name for name in RUNTIME_TABLES)
            connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tables} TO {quoted}"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    provision_runtime_role(Settings(), os.environ.get("POSTGRES_RUNTIME_USER", "hype_news_hub_runtime"), os.environ.get("POSTGRES_RUNTIME_PASSWORD", ""))
    print("Runtime role provisioned; no schema migration or application collection was performed.")
