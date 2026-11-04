"""Real authenticated API regressions against shadow tables in disposable PostgreSQL 16."""
import secrets
from unittest.mock import patch

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.base import Base
from app.database.runtime_security import assert_runtime_role, provision_runtime_role
from app.database.session import TRUSTED_SEARCH_PATH
from app.main import create_app
from app.models import CollectedArticle, EditorialDraftVersion, EditorialVersionSource
from editorial_identity import TestIdentityVerifier
from integration import test_editorial_commands as workflow
from integration import test_runtime_permission_hardening as permissions
from integration.test_persistent_collection import PersistentCollectionCase, post, source
from tests.integration.test_postgresql import alembic_config


class TrustedSchemaTests(PersistentCollectionCase):
    headers = workflow.EditorialCommandTests.headers
    payload = workflow.EditorialCommandTests.payload
    creation = workflow.EditorialCommandTests.creation
    create = workflow.EditorialCommandTests.create
    command = workflow.EditorialCommandTests.command
    read = workflow.EditorialCommandTests.read
    provision = permissions.RuntimePermissionHardeningTests.provision
    create_groups = permissions.RuntimePermissionHardeningTests.create_groups
    remove_groups = permissions.RuntimePermissionHardeningTests.remove_groups

    def setUp(self):
        super().setUp()
        result = self.collect([source(posts=[post()])])
        self.assertEqual(result.status_code, 200, result.text)
        self.story_id = result.json()["stories"][0]["id"]
        self.real_stories = self.client.get("/api/stories").json()
        with self.factory() as session:
            article = session.scalar(select(CollectedArticle))
            self.article_id, self.source_id = str(article.id), str(article.source_id)
        self.private_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        self.private = TestClient(self.private_app)
        self.receipt = self.command(self.command(self.create(), "submit"), "approve")
        self.original = self.read(self.receipt)
        self.assertTrue(self.original["effective_approval"])
        self.schemas = []

    def tearDown(self):
        # Clean adversarial schemas before the next test/provisioning; only this
        # guarded test database is used. No production-role cleanup is implicit.
        self.private.close()
        self.private_app.state.news_repository.engine.dispose()
        self.repository.engine.dispose()
        with self.engine.begin() as connection:
            for schema in self.schemas:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            connection.execute(text("TRUNCATE TABLE " + ", ".join("public." + t.name for t in Base.metadata.sorted_tables
                if t.name.startswith(("editorial_", "ai_processing_")))))
        super().tearDown()

    def new_schema(self, name=None):
        name = name or "hnh_shadow_" + secrets.token_hex(6)
        with self.engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{name}"'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{name}" TO "{self.role}"'))
        self.schemas.append(name)
        return name

    def assert_guard(self, safe):
        with self.repository.engine.connect() as connection:
            if safe:
                assert_runtime_role(connection)
            else:
                with self.assertRaises(ValueError):
                    assert_runtime_role(connection)

    def assert_denied(self, sql):
        with self.assertRaises(SQLAlchemyError) as caught:
            with self.repository.engine.begin() as connection:
                connection.execute(text(sql))
        self.assertEqual(caught.exception.orig.sqlstate, "42501")

    def fill_shadows(self, connection, schema, all_tables=False):
        tables = Base.metadata.sorted_tables if all_tables else [EditorialDraftVersion.__table__, EditorialVersionSource.__table__]
        for table in tables:
            connection.execute(text(f'CREATE TABLE "{schema}".{table.name} AS TABLE public.{table.name}'))
        connection.execute(text(f'UPDATE "{schema}".editorial_draft_versions SET payload = '
            "jsonb_set(payload, '{body}', '\"NEODOBREN TEKST IZ SENKE\"'::jsonb)"))
        connection.execute(text(f'UPDATE "{schema}".editorial_version_sources SET input_text = \'LAŽNI DOKAZ IZ SENKE\''))
        if all_tables:
            connection.execute(text(f'UPDATE "{schema}".stories SET headline = \'LAŽNA PRIČA IZ SENKE\''))

    def force_path(self, schema, *, public_collection=False):
        def altered_path(connection):
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", pg_temp, public, pg_catalog')
        engines = [self.private_app.state.news_repository.engine]
        if public_collection:
            engines.append(self.repository.engine)
        for engine in engines:
            event.listen(engine, "begin", altered_path)
            self.addCleanup(event.remove, engine, "begin", altered_path)

    def assert_real_approved_reads(self):
        current = self.read(self.receipt)
        self.assertEqual(current, self.original)
        response = self.private.get(f"/api/editorial/drafts/{self.receipt['draft_id']}/versions/1", headers=self.headers("reader"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), self.original["current_version"])
        self.assertEqual(self.client.get("/api/stories").json(), self.real_stories)
        with self.factory() as session:
            version = session.get(EditorialDraftVersion, self.original["current_version"]["id"])
            evidence = session.scalar(select(EditorialVersionSource))
            self.assertEqual(version.payload, self.original["current_version"]["payload"])
            self.assertEqual(evidence.input_text, self.original["current_version"]["sources"][0]["input_text"])
            self.assertEqual(evidence.snapshot_hash, self.original["current_version"]["sources"][0]["snapshot_hash"])

    def exercise_attack(self, path):
        # A past unsafe role really creates the copies; the corrected application
        # denies it before the administrator takes ownership of the stray objects.
        schema = self.role if path == "database" else self.new_schema(self.role)
        if path == "database":
            with self.engine.begin() as connection:
                connection.execute(text(f'GRANT CREATE ON DATABASE "{Settings(_env_file=None).postgres_db}" TO "{self.role}" WITH GRANT OPTION'))
            self.schemas.append(schema)
        else:
            grantee = "PUBLIC" if path == "public_schema" else f'"{self.role}"'
            with self.engine.begin() as connection:
                connection.execute(text(f'GRANT CREATE ON SCHEMA "{schema}" TO {grantee}'))
        try:
            self.assert_guard(False)
            with self.repository.engine.begin() as connection:
                if path == "database":
                    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                self.fill_shadows(connection, schema)
            self.assert_guard(False)
            rejected = self.private.get(f"/api/editorial/drafts/{self.receipt['draft_id']}", headers=self.headers("reader"))
            self.assertEqual(rejected.status_code, 503, rejected.text)
            self.assertNotIn("SENKE", rejected.text)
            with self.assertRaises((ValueError, SQLAlchemyError)):
                self.provision()  # Never silently repurpose an owning runtime identity.
            owner = self.engine.dialect.identifier_preparer.quote(Settings(_env_file=None).postgres_user)
            with self.engine.begin() as connection:
                for table in ("editorial_draft_versions", "editorial_version_sources"):
                    connection.execute(text(f'ALTER TABLE "{schema}".{table} OWNER TO {owner}'))
                    connection.execute(text(f'GRANT SELECT ON "{schema}".{table} TO "{self.role}"'))
                if path == "database":
                    connection.execute(text(f'ALTER SCHEMA "{schema}" OWNER TO {owner}'))
                    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{self.role}"'))
            if path == "public_schema":
                with self.assertRaisesRegex(ValueError, "PUBLIC CREATE.*administrator review"):
                    self.provision()
                self.assert_guard(False)
                # Explicit operator decision, confined to this disposable fixture.
                with self.engine.begin() as connection:
                    connection.execute(text(f'REVOKE CREATE ON SCHEMA "{schema}" FROM PUBLIC RESTRICT'))
            self.provision()
            self.provision()
            self.assert_guard(True)
            self.assert_denied('CREATE SCHEMA hnh_forbidden_schema')
            self.assert_denied(f'CREATE TABLE "{schema}".forbidden (id integer)')
            self.force_path(schema, public_collection=True)
            with self.repository.engine.connect() as connection:
                # A negative control proves that this path really selects a false
                # copy when SQL omits the schema, while the APIs stay authoritative.
                self.assertEqual(connection.execute(text("SELECT payload ->> 'body' FROM editorial_draft_versions LIMIT 1")).scalar_one(),
                                 "NEODOBREN TEKST IZ SENKE")
            self.assert_real_approved_reads()
        finally:
            with self.engine.begin() as connection:
                if path == "public_schema":
                    connection.execute(text(f'REVOKE CREATE ON SCHEMA "{schema}" FROM PUBLIC RESTRICT'))

    def test_direct_database_create_shadow_attack(self):
        self.exercise_attack("database")

    def test_direct_schema_create_shadow_attack(self):
        self.exercise_attack("schema")

    def test_public_schema_create_shadow_attack(self):
        self.exercise_attack("public_schema")

    def test_readonly_existing_shadows_and_session_drift_cannot_redirect_reads_or_writes(self):
        schema = self.new_schema()
        with self.engine.begin() as connection:
            self.fill_shadows(connection, schema, all_tables=True)
            connection.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{self.role}"'))
            # Runtime security must use pg_catalog explicitly even if its session
            # path puts an unrelated pg_roles view ahead of the real catalog.
            connection.execute(text(f'CREATE VIEW "{schema}".pg_roles AS SELECT * FROM pg_catalog.pg_roles WHERE false'))
        self.force_path(schema, public_collection=True)
        self.assert_guard(True)
        self.assert_real_approved_reads()
        saved = self.command(self.receipt, "revisions")
        self.assertEqual(saved["status"], "editing")
        self.assertFalse(self.read(saved)["effective_approval"])
        result = self.collect([source(posts=[post(content="Legitimna izmena prikupljenog članka.")])])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["X-Collection-New-Articles"], "0")
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text(f'SELECT count(*) FROM "{schema}".editorial_draft_versions')).scalar_one(), 1)
        detail = self.private.get(f"/api/editorial/drafts/{saved['draft_id']}/versions/1", headers=self.headers("reader"))
        self.assertEqual(detail.json(), self.original["current_version"])

    def test_temporary_relation_cannot_override_qualified_orm_even_with_path_drift(self):
        with self.repository.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text('CREATE TEMP TABLE editorial_draft_versions AS TABLE public.editorial_draft_versions'))
                connection.execute(text("UPDATE pg_temp.editorial_draft_versions SET payload = '{}'::jsonb"))
                connection.execute(text('SET LOCAL search_path TO pg_temp, public, pg_catalog'))
                self.assertEqual(connection.execute(text('SELECT payload FROM editorial_draft_versions')).scalar_one(), {})
                with Session(bind=connection) as session:
                    version = session.scalar(select(EditorialDraftVersion))
                    self.assertEqual(version.payload, self.original["current_version"]["payload"])
                # Runtime owns a temporary table too: it cannot pass the owning-role
                # boundary while that object exists. Normal application code uses none.
                with self.assertRaises(ValueError):
                    assert_runtime_role(connection)
            finally:
                transaction.rollback()
        self.assert_guard(True)

    def test_pool_checkout_and_role_defaults_restore_trusted_path(self):
        schema = self.new_schema()
        with self.engine.begin() as connection:
            connection.execute(text(f'ALTER ROLE "{self.role}" SET search_path TO "{schema}", public'))
        try:
            self.repository.engine.dispose()
            with self.repository.engine.begin() as connection:
                self.assertEqual(connection.execute(text('SHOW search_path')).scalar_one(), TRUSTED_SEARCH_PATH)
                connection.execute(text(f'SET SESSION search_path TO "{schema}", public'))
            with self.repository.engine.connect() as connection:
                self.assertEqual(connection.execute(text('SHOW search_path')).scalar_one(), TRUSTED_SEARCH_PATH)
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'ALTER ROLE "{self.role}" RESET search_path'))

    def test_public_database_create_requires_explicit_admin_review(self):
        database = Settings(_env_file=None).postgres_db
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT CREATE ON DATABASE "{database}" TO PUBLIC'))
        try:
            self.assert_guard(False)
            with self.assertRaisesRegex(ValueError, "PUBLIC CREATE.*administrator review"):
                self.provision()
            self.assert_guard(False)
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'REVOKE CREATE ON DATABASE "{database}" FROM PUBLIC RESTRICT'))
        self.provision()
        self.assert_guard(True)
        self.assert_real_approved_reads()

    def test_nested_create_privileges_and_noinherit_set_role_paths_are_detached(self):
        schema = self.new_schema()
        parent, child, observer = self.create_groups(3)
        database = Settings(_env_file=None).postgres_db
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT CREATE ON DATABASE "{database}" TO "{parent}"'))
            connection.execute(text(f'GRANT CREATE ON SCHEMA "{schema}" TO "{parent}"'))
            connection.execute(text(f'GRANT "{parent}" TO "{child}" WITH INHERIT TRUE, SET TRUE'))
            connection.execute(text(f'GRANT "{parent}" TO "{observer}" WITH INHERIT TRUE'))
            connection.execute(text(f'GRANT "{child}" TO "{self.role}" WITH INHERIT FALSE, SET TRUE'))
        self.assert_guard(False)
        with self.repository.engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{parent}"'))
            self.assertTrue(connection.execute(text('SELECT pg_catalog.has_database_privilege(current_user, current_database(), \'CREATE\')')).scalar_one())
        self.provision()
        self.assert_guard(True)
        self.assert_denied(f'SET LOCAL ROLE "{parent}"')
        with self.engine.connect() as connection:
            self.assertTrue(connection.execute(text('SELECT pg_catalog.has_schema_privilege(:role, :schema, \'CREATE\')'),
                {"role": observer, "schema": schema}).scalar_one())
        self.assert_real_approved_reads()

    def test_database_schema_and_table_acl_repair_rolls_back_together(self):
        schema = self.new_schema()
        database = Settings(_env_file=None).postgres_db
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT CREATE ON DATABASE "{database}" TO "{self.role}"'))
            connection.execute(text(f'GRANT CREATE ON SCHEMA "{schema}" TO "{self.role}" WITH GRANT OPTION'))
            connection.execute(text(f'GRANT TRUNCATE ON collection_runs TO "{self.role}"'))
        try:
            with patch('app.database.runtime_security.assert_runtime_role', side_effect=ValueError('Injected final check failure')):
                with self.assertRaises(ValueError):
                    provision_runtime_role(Settings(_env_file=None), self.role, secrets.token_hex(32))
            self.repository.engine.dispose()
            with self.repository.engine.connect() as connection:
                self.assertTrue(connection.execute(text('SELECT pg_catalog.has_database_privilege(current_user, current_database(), \'CREATE\')')).scalar_one())
                self.assertTrue(connection.execute(text('SELECT pg_catalog.has_schema_privilege(current_user, :schema, \'CREATE WITH GRANT OPTION\')'),
                    {"schema": schema}).scalar_one())
                self.assertTrue(connection.execute(text('SELECT pg_catalog.has_table_privilege(current_user, \'collection_runs\', \'TRUNCATE\')')).scalar_one())
        finally:
            self.provision()
        self.assert_guard(True)

    def test_nonpublic_schema_ownership_is_rejected_consistently(self):
        schema = self.new_schema()
        owner = self.engine.dialect.identifier_preparer.quote(Settings(_env_file=None).postgres_user)
        with self.engine.begin() as connection:
            connection.execute(text(f'ALTER SCHEMA "{schema}" OWNER TO "{self.role}"'))
        try:
            self.assert_guard(False)
            with self.assertRaises(SQLAlchemyError):
                self.provision()
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'ALTER SCHEMA "{schema}" OWNER TO {owner}'))
            self.provision()
        self.assert_guard(True)

    def test_database_ownership_is_rejected_consistently(self):
        config = Settings(_env_file=None)
        owner = self.engine.dialect.identifier_preparer.quote(config.postgres_user)
        with self.engine.begin() as connection:
            connection.execute(text(f'ALTER DATABASE "{config.postgres_db}" OWNER TO "{self.role}"'))
        try:
            self.assert_guard(False)
            with self.assertRaises(SQLAlchemyError):
                self.provision()
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'ALTER DATABASE "{config.postgres_db}" OWNER TO {owner}'))
            self.provision()
        self.assert_guard(True)
        self.assert_real_approved_reads()

    def test_owner_session_cannot_masquerade_as_a_restricted_runtime_login(self):
        with self.engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{self.role}"'))
            with self.assertRaises(ValueError):
                assert_runtime_role(connection)
            # Provisioning explicitly inspects a named target using an owner
            # connection; that is distinct from authorizing the current session.
            assert_runtime_role(connection, role_name=self.role)

    def test_direct_public_schema_create_is_repaired_without_changing_other_roles(self):
        observer, = self.create_groups(1)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT CREATE ON SCHEMA public TO "{self.role}" WITH GRANT OPTION'))
            connection.execute(text(f'GRANT CREATE ON SCHEMA public TO "{observer}"'))
        self.assert_guard(False)
        self.provision()
        self.assert_guard(True)
        with self.engine.connect() as connection:
            self.assertTrue(connection.execute(text("SELECT pg_catalog.has_schema_privilege(:role, 'public', 'CREATE')"),
                {"role": observer}).scalar_one())
            self.assertFalse(connection.execute(text("SELECT pg_catalog.has_schema_privilege(:role, 'public', 'CREATE WITH GRANT OPTION')"),
                {"role": self.role}).scalar_one())

    def test_owner_migration_connection_ignores_shadow_version_table(self):
        schema = self.new_schema()
        with self.engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE "{schema}".alembic_version (version_num text)'))
            connection.execute(text(f'INSERT INTO "{schema}".alembic_version VALUES (\'untrusted\')'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            command.upgrade(alembic_config(connection), '20261101_06')
            command.check(alembic_config(connection))
            self.assertEqual(connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one(), 'untrusted')
        self.assert_real_approved_reads()
