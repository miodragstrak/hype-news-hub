"""Runtime checks and explicit, operator-invoked least-privilege provisioning."""
import json
import os
import re

from sqlalchemy import text

from app.core.config import Settings
from app.database.session import create_database_engine

RUNTIME_TABLES = (
    "news_sources", "collected_articles", "article_identities", "stories",
    "story_articles", "collection_runs", "collection_source_results",
)
EDITORIAL_HISTORY_TABLES = (
    "editorial_draft_versions", "editorial_version_sources", "editorial_decisions", "editorial_events",
)
# Collection upserts and mutable editorial heads need UPDATE; immutable history
# is append-only. No application operation needs deletion or privilege delegation.
RUNTIME_PRIVILEGE_ALLOWLIST = {
    **{table: ("SELECT", "INSERT", "UPDATE") for table in RUNTIME_TABLES},
    "editorial_drafts": ("SELECT", "INSERT", "UPDATE"),
    **{table: ("SELECT", "INSERT") for table in EDITORIAL_HISTORY_TABLES},
    "ai_processing_runs": ("SELECT", "INSERT", "UPDATE"),
    "ai_processing_events": ("SELECT", "INSERT"),
}
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


def _public_table_grants(connection, policy=None):
    """Report shared ACLs; provisioning must never silently rewrite other users' access."""
    policy = RUNTIME_PRIVILEGE_ALLOWLIST if policy is None else policy
    return connection.execute(text("""SELECT c.relname, NULL AS attname, acl.privilege_type
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) acl
        WHERE n.nspname = 'public' AND c.relname::pg_catalog.text = ANY(:tables) AND acl.grantee = 0
        UNION
        SELECT c.relname, a.attname, acl.privilege_type
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) acl
        WHERE n.nspname = 'public' AND c.relname::pg_catalog.text = ANY(:tables) AND acl.grantee = 0
        ORDER BY 1, 2, 3"""), {"tables": list(policy)}).all()

def _public_create_grants(connection):
    return connection.execute(text("""SELECT 'database', d.datname FROM pg_catalog.pg_database d
        CROSS JOIN LATERAL pg_catalog.aclexplode(d.datacl) acl
        WHERE d.datname = pg_catalog.current_database() AND acl.grantee = 0 AND acl.privilege_type = 'CREATE'
        UNION SELECT 'schema', n.nspname FROM pg_catalog.pg_namespace n
        CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) acl
        WHERE acl.grantee = 0 AND acl.privilege_type = 'CREATE' ORDER BY 1, 2""")).all()


def assert_runtime_role(connection, *, role_name: str | None = None, policy=None) -> None:
    """Check effective rights, including PUBLIC and SET ROLE membership paths."""
    policy = RUNTIME_PRIVILEGE_ALLOWLIST if policy is None else policy
    unsafe = connection.execute(text("""WITH runtime AS (
        SELECT oid, rolname FROM pg_catalog.pg_roles WHERE rolname = coalesce(CAST(:role_name AS pg_catalog.name), current_user)
    ), managed AS (
        SELECT c.oid, c.relacl, policy.value AS allowed
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_catalog.jsonb_each(CAST(:policy AS pg_catalog.jsonb)) policy ON policy.key = c.relname::pg_catalog.text
        WHERE n.nspname = 'public'
    ) SELECT (CAST(:role_name AS pg_catalog.name) IS NULL AND session_user <> current_user)
        OR NOT EXISTS (SELECT 1 FROM runtime) OR EXISTS (SELECT 1 FROM runtime u WHERE
        EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE pg_catalog.pg_has_role(u.oid, r.oid, 'MEMBER')
            AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls))
        OR pg_catalog.has_database_privilege(u.oid, pg_catalog.current_database(), 'CREATE')
        OR EXISTS (SELECT 1 FROM pg_catalog.pg_database d WHERE pg_catalog.pg_has_role(u.oid, d.datdba, 'MEMBER'))
        OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n WHERE pg_catalog.has_schema_privilege(u.oid, n.oid, 'CREATE')
            OR pg_catalog.pg_has_role(u.oid, n.nspowner, 'MEMBER'))
        OR EXISTS (SELECT 1 FROM pg_catalog.pg_class c WHERE pg_catalog.pg_has_role(u.oid, c.relowner, 'MEMBER'))
        OR EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member = u.oid)
        OR EXISTS (SELECT 1 FROM managed c CROSS JOIN pg_catalog.unnest(CAST(:table_privileges AS pg_catalog.text[])) p(privilege)
            WHERE (NOT (c.allowed ? p.privilege) AND pg_catalog.has_table_privilege(u.oid, c.oid, p.privilege))
                OR pg_catalog.has_table_privilege(u.oid, c.oid, p.privilege || ' WITH GRANT OPTION'))
        OR EXISTS (SELECT 1 FROM managed c CROSS JOIN pg_catalog.unnest(CAST(:column_privileges AS pg_catalog.text[])) p(privilege)
            WHERE (NOT (c.allowed ? p.privilege) AND pg_catalog.has_any_column_privilege(u.oid, c.oid, p.privilege))
                OR pg_catalog.has_any_column_privilege(u.oid, c.oid, p.privilege || ' WITH GRANT OPTION'))
        OR EXISTS (SELECT 1 FROM managed c CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) acl WHERE acl.grantee = 0)
        OR EXISTS (SELECT 1 FROM managed c JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) acl
            WHERE a.attnum > 0 AND NOT a.attisdropped AND acl.grantee = 0)
    )"""), {"role_name": role_name, "policy": json.dumps(policy),
            "table_privileges": list(TABLE_PRIVILEGES), "column_privileges": list(COLUMN_PRIVILEGES)}).scalar_one()
    if unsafe:
        raise ValueError("PostgreSQL mode requires a restricted runtime role without database/schema CREATE, ownership, memberships, "
                         "PUBLIC table grants or privileges outside the runtime allowlists (including grant options).")

def provision_runtime_role(config: Settings, role: str, password: str, *, policy=None) -> None:
    policy = RUNTIME_PRIVILEGE_ALLOWLIST if policy is None else policy
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role) or role.startswith("pg_") or role == config.postgres_user:
        raise ValueError("Choose a separate, non-system PostgreSQL runtime role name.")
    if len(password) < 24:
        raise ValueError("POSTGRES_RUNTIME_PASSWORD must contain at least 24 characters.")
    engine = create_database_engine(config)
    try:
        with engine.begin() as connection:
            public_create = _public_create_grants(connection)
            if public_create:
                details = "; ".join(f"{kind} {name}: CREATE" for kind, name in public_create)
                raise ValueError("PUBLIC CREATE grants require administrator review before runtime provisioning. "
                                 "Review shared consumers, replace intentional access with named-role grants, explicitly "
                                 "revoke PUBLIC CREATE on the reported database/schemas, then rerun provisioning. "
                                 "No shared ACLs were changed. " + details)
            public_grants = _public_table_grants(connection, policy)
            if public_grants:
                details = "; ".join(f"public.{table}" + (f"({column})" if column else "") + f": {privilege}"
                                    for table, column, privilege in public_grants)
                raise ValueError("PUBLIC grants on managed tables require administrator review before runtime provisioning. "
                                 "Replace intentional shared access with named-role grants, explicitly revoke the PUBLIC "
                                 "table/column grants, then rerun provisioning. No shared ACLs were changed. " + details)
            connection.execute(text("SELECT pg_catalog.set_config('hnh.runtime_role', :role, true), pg_catalog.set_config('hnh.runtime_password', :password, true)"), {"role": role, "password": password})
            # Passwords are bound parameters above, never interpolated into SQL logs.
            connection.execute(text("""DO $$ DECLARE runtime_name text := pg_catalog.current_setting('hnh.runtime_role'); parent_name text;
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = runtime_name) THEN
                        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = runtime_name
                            AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
                            OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE pg_catalog.pg_has_role(runtime_name::pg_catalog.name, r.oid, 'MEMBER') AND (
                                r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
                                OR EXISTS (SELECT 1 FROM pg_catalog.pg_class c WHERE c.relowner = r.oid)
                                OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspowner = r.oid)
                                OR EXISTS (SELECT 1 FROM pg_catalog.pg_database d WHERE d.datdba = r.oid)))
                            OR EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_roles r ON r.oid = c.relowner WHERE r.rolname = runtime_name)
                            OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n JOIN pg_catalog.pg_roles r ON r.oid = n.nspowner WHERE r.rolname = runtime_name)
                            OR EXISTS (SELECT 1 FROM pg_catalog.pg_database d JOIN pg_catalog.pg_roles r ON r.oid = d.datdba WHERE r.rolname = runtime_name)
                        THEN RAISE EXCEPTION 'Refusing to repurpose a privileged or owning role'; END IF;
                    ELSE
                        EXECUTE pg_catalog.format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', runtime_name);
                    END IF;
                    -- A dedicated runtime receives explicit grants only. Detach
                    -- non-owning group paths without changing shared group ACLs.
                    FOR parent_name IN SELECT DISTINCT p.rolname FROM pg_catalog.pg_auth_members m
                        JOIN pg_catalog.pg_roles u ON u.oid = m.member JOIN pg_catalog.pg_roles p ON p.oid = m.roleid
                        WHERE u.rolname = runtime_name LOOP
                        EXECUTE pg_catalog.format('REVOKE %I FROM %I', parent_name, runtime_name);
                    END LOOP;
                    EXECUTE pg_catalog.format('ALTER ROLE %I NOINHERIT', runtime_name);
                    EXECUTE pg_catalog.format('ALTER ROLE %I PASSWORD %L', runtime_name, pg_catalog.current_setting('hnh.runtime_password'));
                    EXECUTE pg_catalog.format('GRANT CONNECT ON DATABASE %I TO %I', pg_catalog.current_database(), runtime_name);
                    EXECUTE pg_catalog.format('GRANT USAGE ON SCHEMA public TO %I', runtime_name);
                    EXECUTE pg_catalog.format('GRANT EXECUTE ON FUNCTION public.hnh_identity_hash(text) TO %I', runtime_name);
                END $$"""))
            quoted = engine.dialect.identifier_preparer.quote(role)
            database = engine.dialect.identifier_preparer.quote(connection.execute(text("SELECT pg_catalog.current_database()")).scalar_one())
            connection.execute(text(f"REVOKE CREATE ON DATABASE {database} FROM {quoted} RESTRICT"))
            schemas = connection.execute(text("SELECT nspname FROM pg_catalog.pg_namespace ORDER BY nspname")).scalars().all()
            for schema in schemas:
                target_schema = engine.dialect.identifier_preparer.quote(schema)
                connection.execute(text(f"REVOKE CREATE ON SCHEMA {target_schema} FROM {quoted} RESTRICT"))
            columns = connection.execute(text("""SELECT c.relname, pg_catalog.array_agg(a.attname ORDER BY a.attnum)
                FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                WHERE n.nspname = 'public' AND c.relname::pg_catalog.text = ANY(:tables) GROUP BY c.relname"""),
                {"tables": list(policy)}).all()
            columns = dict(columns)
            if columns.keys() != policy.keys():
                raise ValueError("Apply all Alembic migrations before provisioning the runtime role.")
            for table, privileges in policy.items():
                target = "public." + engine.dialect.identifier_preparer.quote(table)
                names = ", ".join(engine.dialect.identifier_preparer.quote(name) for name in columns[table])
                # Table revocation alone leaves column ACLs behind. RESTRICT
                # prevents silently cascading into grants made to unrelated roles.
                connection.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE {target} FROM {quoted} RESTRICT"))
                connection.execute(text(f"REVOKE ALL PRIVILEGES ({names}) ON TABLE {target} FROM {quoted} RESTRICT"))
                connection.execute(text(f"GRANT {', '.join(privileges)} ON TABLE {target} TO {quoted}"))
            connection.execute(text(f"GRANT EXECUTE ON FUNCTION public.hnh_editorial_snapshot_hash("
                f"uuid, uuid, text, text, text, text, text, timestamptz, text, timestamptz) TO {quoted}"))
            # Validate the named role, not this owner connection. Unexpected grant
            # paths/dependencies fail the transaction instead of reporting success.
            assert_runtime_role(connection, role_name=role, policy=policy)
    finally:
        engine.dispose()

if __name__ == "__main__":
    provision_runtime_role(Settings(), os.environ.get("POSTGRES_RUNTIME_USER", "hype_news_hub_runtime"), os.environ.get("POSTGRES_RUNTIME_PASSWORD", ""))
    print("Runtime role provisioned; no schema migration or application collection was performed.")
