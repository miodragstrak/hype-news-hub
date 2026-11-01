"""Effective runtime permissions in the guarded, disposable PostgreSQL database."""
import secrets
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.database.runtime_security import EDITORIAL_HISTORY_TABLES, RUNTIME_TABLES, assert_runtime_role, provision_runtime_role
from app.models import ArticleIdentity, CollectedArticle, CollectionRun
from integration.test_persistent_collection import PersistentCollectionCase, post, source


class RuntimePermissionHardeningTests(PersistentCollectionCase):
    def provision(self):
        provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())

    def collection_snapshot(self):
        with self.engine.connect() as connection:
            return {table: connection.execute(text(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM public.{table} t"
            )).scalar_one() for table in RUNTIME_TABLES}

    def effective_delete(self, role, table="collection_runs"):
        return self.effective_privilege(role, table, "DELETE")

    def effective_privilege(self, role, table, privilege):
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT has_table_privilege(:role, :table, :privilege)"),
                                      {"role": role, "table": "public." + table, "privilege": privilege}).scalar_one()

    def assert_restricted(self):
        with self.repository.engine.connect() as connection:
            assert_runtime_role(connection)
            for table in (*RUNTIME_TABLES, "editorial_drafts", *EDITORIAL_HISTORY_TABLES):
                expected = {"SELECT", "INSERT"} if table in EDITORIAL_HISTORY_TABLES else {"SELECT", "INSERT", "UPDATE"}
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    allowed = connection.execute(text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                                                 {"table": "public." + table, "privilege": privilege}).scalar_one()
                    self.assertEqual(allowed, privilege in expected, (table, privilege))
                    self.assertFalse(connection.execute(text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                        {"table": "public." + table, "privilege": privilege + " WITH GRANT OPTION"}).scalar_one(), (table, privilege))
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    self.assertEqual(connection.execute(text("SELECT has_any_column_privilege(current_user, :table, :privilege)"),
                        {"table": "public." + table, "privilege": privilege}).scalar_one(), privilege in expected, (table, privilege))
                    self.assertFalse(connection.execute(text("SELECT has_any_column_privilege(current_user, :table, :privilege)"),
                        {"table": "public." + table, "privilege": privilege + " WITH GRANT OPTION"}).scalar_one(), (table, privilege))
            self.assertEqual(connection.execute(text("SELECT count(*) FROM pg_auth_members WHERE member = "
                                                    "(SELECT oid FROM pg_roles WHERE rolname = current_user)")).scalar_one(), 0)
            self.assertFalse(connection.execute(text("SELECT rolinherit FROM pg_roles WHERE rolname = current_user")).scalar_one())

    def assert_delete_denied(self, table):
        self.assert_sql_denied("DELETE FROM public." + table)

    def assert_sql_denied(self, sql):
        with self.assertRaises(SQLAlchemyError) as caught:
            with self.repository.engine.begin() as connection:
                connection.execute(text(sql))
        # Verify permission denial, rather than passing because a FK blocked it.
        self.assertEqual(caught.exception.orig.sqlstate, "42501")

    def create_groups(self, count):
        groups = ["hnh_permission_group_" + secrets.token_hex(6) for _ in range(count)]
        with self.engine.begin() as connection:
            for role in groups:
                connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        self.addCleanup(self.remove_groups, groups)
        return groups

    def remove_groups(self, groups):
        with self.engine.begin() as connection:
            for role in reversed(groups):
                connection.execute(text(f'DROP OWNED BY "{role}"'))
                connection.execute(text(f'DROP ROLE "{role}"'))

    def revoke_public_delete(self):
        with self.engine.begin() as connection:
            connection.execute(text("REVOKE DELETE ON TABLE " + ", ".join("public." + name for name in RUNTIME_TABLES) + " FROM PUBLIC"))

    def test_runtime_cannot_delete_any_committed_collection_record(self):
        response = self.collect([source(posts=[post()])])
        self.assertEqual(response.status_code, 200, response.text)
        before = self.collection_snapshot()
        self.assertTrue(all(before.values()), "Every managed collection table must contain a committed row")
        self.assert_restricted()
        for table in RUNTIME_TABLES:
            with self.subTest(table=table):
                self.assert_delete_denied(table)
        self.assertEqual(self.collection_snapshot(), before)

    def test_previously_granted_delete_is_revoked_idempotently_and_recollection_works(self):
        first = self.collect([source(posts=[post()])])
        self.assertEqual(first.status_code, 200, first.text)
        with self.engine.begin() as connection:
            connection.execute(text("GRANT DELETE ON TABLE " + ", ".join("public." + name for name in RUNTIME_TABLES) + f' TO "{self.role}"'))
            connection.execute(text(f'ALTER ROLE "{self.role}" INHERIT'))
        self.assertTrue(self.effective_delete(self.role))
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        before = self.collection_snapshot()
        self.provision()
        self.provision()
        self.assert_restricted()
        self.assert_delete_denied("collection_runs")
        self.assertEqual(self.collection_snapshot(), before)
        repeated = self.collect([source(posts=[post(content="Updated source content", url="https://source.invalid/item/?utm_source=test")])])
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(repeated.json()["stories"][0]["id"], first.json()["stories"][0]["id"])
        self.assertEqual(self.count(CollectedArticle), 1)
        self.assertEqual(self.count(CollectionRun), 2)
        with self.factory() as session:
            self.assertEqual(session.scalars(select(CollectedArticle)).one().content, "Updated source content")
        self.assertGreater(self.count(ArticleIdentity), 2)

    def test_public_delete_requires_explicit_administrator_review(self):
        self.collect([source(posts=[post()])])
        self.addCleanup(self.revoke_public_delete)
        with self.engine.begin() as connection:
            connection.execute(text("GRANT DELETE ON TABLE " + ", ".join("public." + name for name in RUNTIME_TABLES) + " TO PUBLIC"))
        self.assertTrue(self.effective_delete(self.role))
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        with self.assertRaisesRegex(ValueError, "PUBLIC grants.*administrator review"):
            self.provision()
        self.assertTrue(self.effective_delete(self.role), "Provisioning must not silently rewrite shared PUBLIC ACLs")
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        self.revoke_public_delete()  # Explicit owner remediation in this disposable database.
        self.provision()
        self.assert_restricted()
        self.assert_delete_denied("collection_runs")
        self.assertEqual(self.client.get("/api/stories").status_code, 200)

    def test_nested_inherited_delete_is_detached_without_changing_shared_group_grants(self):
        parent, intermediate, observer = self.create_groups(3)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT ALL ON TABLE collection_runs TO "{parent}"'))
            connection.execute(text(f'GRANT "{parent}" TO "{intermediate}" WITH INHERIT TRUE, SET TRUE'))
            connection.execute(text(f'GRANT "{intermediate}" TO "{self.role}" WITH INHERIT TRUE, SET TRUE'))
            connection.execute(text(f'GRANT "{parent}" TO "{observer}" WITH INHERIT TRUE'))
        self.assertTrue(self.effective_delete(self.role))
        for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
            self.assertTrue(self.effective_privilege(self.role, "collection_runs", privilege))
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        self.provision()
        self.provision()
        self.assert_restricted()
        self.assertTrue(self.effective_delete(parent))
        self.assertTrue(self.effective_delete(observer))
        for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
            self.assertTrue(self.effective_privilege(observer, "collection_runs", privilege))
        with self.assertRaises(SQLAlchemyError) as caught:
            with self.repository.engine.begin() as connection:
                connection.execute(text(f'SET LOCAL ROLE "{parent}"'))
        self.assertEqual(caught.exception.orig.sqlstate, "42501")
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)

    def test_noinherit_does_not_hide_a_set_role_delete_path(self):
        parent, = self.create_groups(1)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT ALL ON TABLE collection_runs TO "{parent}"'))
            connection.execute(text(f'GRANT "{parent}" TO "{self.role}" WITH INHERIT FALSE, SET TRUE'))
        self.assertFalse(self.effective_delete(self.role))
        self.assertFalse(self.effective_privilege(self.role, "collection_runs", "TRUNCATE"))
        with self.repository.engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{parent}"'))
            self.assertTrue(connection.execute(text("SELECT has_table_privilege(current_user, 'collection_runs', 'DELETE')")).scalar_one())
            self.assertTrue(connection.execute(text("SELECT has_table_privilege(current_user, 'collection_runs', 'TRUNCATE')")).scalar_one())
        # The connection has reset its local role, but the membership itself is unsafe.
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        self.provision()
        self.assert_restricted()
        with self.assertRaises(SQLAlchemyError) as caught:
            with self.repository.engine.begin() as connection:
                connection.execute(text(f'SET LOCAL ROLE "{parent}"'))
        self.assertEqual(caught.exception.orig.sqlstate, "42501")

    def test_failed_effective_privilege_verification_rolls_back_provisioning(self):
        parent, = self.create_groups(1)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT DELETE ON TABLE collection_runs TO "{self.role}"'))
            connection.execute(text(f'GRANT "{parent}" TO "{self.role}" WITH INHERIT TRUE'))
        try:
            with patch("app.database.runtime_security.assert_runtime_role", side_effect=ValueError("Synthetic unsafe effective grant")):
                with self.assertRaises(ValueError):
                    provision_runtime_role(Settings(_env_file=None), self.role, secrets.token_hex(32))
            self.assertTrue(self.effective_delete(self.role))
            with self.engine.connect() as connection:
                self.assertTrue(connection.execute(text("SELECT pg_has_role(:runtime, :parent, 'MEMBER')"),
                                                   {"runtime": self.role, "parent": parent}).scalar_one())
            # A new connection with the original password still works: credential
            # rotation and membership/ACL changes all rolled back together.
            self.repository.engine.dispose()
            with self.repository.engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT current_user")).scalar_one(), self.role)
        finally:
            self.provision()
        self.assert_restricted()

    def test_committed_truncate_exploit_is_removed_by_exact_idempotent_allowlists(self):
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)
        with self.engine.begin() as connection:
            self.assertEqual(connection.execute(text("SHOW server_version_num")).scalar_one()[:2], "16")
            connection.execute(text("GRANT ALL ON TABLE " + ", ".join("public." + table for table in RUNTIME_TABLES) + f' TO "{self.role}"'))
            # Reproduce the old provisioner's result: DELETE alone was removed.
            connection.execute(text("REVOKE DELETE ON TABLE " + ", ".join("public." + table for table in RUNTIME_TABLES) + f' FROM "{self.role}"'))
        self.assertFalse(self.effective_delete(self.role))
        self.assertEqual(self.client.get("/api/stories").status_code, 503, "The new guard must reject this legacy state")
        with self.repository.engine.begin() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM collection_source_results")).scalar_one(), 1)
            connection.execute(text("TRUNCATE public.collection_source_results"))
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM collection_source_results")).scalar_one(), 0)
        # The destructive statement above really committed; it was not an ACL-only
        # probe or a transaction rolled back before the application could see it.
        self.provision()
        self.provision()
        self.assert_restricted()
        before = self.collection_snapshot()
        for sql in (
            "TRUNCATE public.collection_source_results",
            "CREATE TRIGGER forbidden_trigger BEFORE UPDATE ON public.collection_runs FOR EACH ROW "
            "EXECUTE FUNCTION public.hnh_editorial_immutable()",
        ):
            with self.subTest(sql=sql):
                self.assert_sql_denied(sql)
        self.assertEqual(self.collection_snapshot(), before)
        self.assertEqual(self.client.get("/api/stories").status_code, 200)
        repeated = self.collect([source(posts=[post(content="Recollected after ACL correction")])])
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")

    def test_each_direct_privilege_drift_fails_closed_until_reprovisioned(self):
        for table in RUNTIME_TABLES:
            for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                with self.subTest(table=table, privilege=privilege):
                    with self.engine.begin() as connection:
                        connection.execute(text(f'GRANT {privilege} ON TABLE public.{table} TO "{self.role}"'))
                    self.assertTrue(self.effective_privilege(self.role, table, privilege))
                    self.assertEqual(self.client.get("/api/stories").status_code, 503)
                    self.provision()
                    self.assertFalse(self.effective_privilege(self.role, table, privilege))
                    self.assertEqual(self.client.get("/api/stories").status_code, 200)
        self.assert_restricted()

    def test_column_rights_history_updates_and_grant_options_cannot_escape_allowlists(self):
        drifts = (
            'GRANT REFERENCES (id) ON collected_articles TO "{role}"',
            'GRANT UPDATE (payload) ON editorial_draft_versions TO "{role}"',
            'GRANT SELECT (id) ON collection_runs TO "{role}" WITH GRANT OPTION',
            'GRANT SELECT ON collection_runs TO "{role}" WITH GRANT OPTION',
            'GRANT ALL ON editorial_events, editorial_drafts TO "{role}"',
        )
        for grant in drifts:
            with self.subTest(grant=grant):
                with self.engine.begin() as connection:
                    connection.execute(text(grant.format(role=self.role)))
                self.assertEqual(self.client.get("/api/stories").status_code, 503)
                self.provision()
                self.assert_restricted()
                self.assertEqual(self.client.get("/api/stories").status_code, 200)

    def test_public_table_and_column_drift_is_preserved_until_reviewed_by_owner(self):
        for privileges in ("TRUNCATE", "REFERENCES", "TRIGGER", "SELECT (id)", "REFERENCES (id)"):
            with self.subTest(privileges=privileges):
                grant = f"GRANT {privileges} ON TABLE collection_runs TO PUBLIC"
                revoke = f"REVOKE {privileges} ON TABLE collection_runs FROM PUBLIC"
                with self.engine.begin() as connection:
                    connection.execute(text(grant))
                try:
                    self.assertEqual(self.client.get("/api/stories").status_code, 503)
                    with self.assertRaisesRegex(ValueError, "public.collection_runs"):
                        provision_runtime_role(Settings(_env_file=None), self.role, secrets.token_hex(32))
                    self.assertEqual(self.client.get("/api/stories").status_code, 503)
                    # The rejection happens before any credential/role mutation.
                    self.repository.engine.dispose()
                    with self.repository.engine.connect() as connection:
                        self.assertEqual(connection.execute(text("SELECT current_user")).scalar_one(), self.role)
                        function = "has_any_column_privilege" if "(" in privileges else "has_table_privilege"
                        self.assertTrue(connection.execute(text(f"SELECT {function}(current_user, 'collection_runs', :privilege)"),
                            {"privilege": privileges.split()[0]}).scalar_one())
                finally:
                    with self.engine.begin() as connection:
                        connection.execute(text(revoke))
                self.provision()
                self.assertEqual(self.client.get("/api/stories").status_code, 200)
        self.assert_restricted()

    def test_dependent_grants_require_administrator_review_without_cascading(self):
        observer, = self.create_groups(1)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT SELECT ON collection_runs TO "{self.role}" WITH GRANT OPTION'))
            connection.execute(text(f'GRANT TRUNCATE ON news_sources TO "{self.role}"'))
        with self.repository.engine.begin() as connection:
            connection.execute(text(f'GRANT SELECT ON collection_runs TO "{observer}"'))
        self.assertEqual(self.client.get("/api/stories").status_code, 503)
        try:
            with self.assertRaises(SQLAlchemyError) as caught:
                provision_runtime_role(Settings(_env_file=None), self.role, secrets.token_hex(32))
            self.assertEqual(caught.exception.orig.sqlstate, "2BP01")
            self.assertTrue(self.effective_privilege(observer, "collection_runs", "SELECT"))
            self.assertTrue(self.effective_privilege(self.role, "collection_runs", "SELECT WITH GRANT OPTION"))
            self.assertTrue(self.effective_privilege(self.role, "news_sources", "TRUNCATE"),
                            "Earlier ACL changes must roll back when a later dependent grant blocks revocation")
            self.repository.engine.dispose()
            with self.repository.engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT current_user")).scalar_one(), self.role)
        finally:
            # Explicit, reviewed cleanup of the intentionally dependent fixture.
            with self.repository.engine.begin() as connection:
                connection.execute(text(f'REVOKE SELECT ON collection_runs FROM "{observer}"'))
            self.provision()
        self.assert_restricted()

    def test_unrelated_named_role_grants_are_not_rewritten(self):
        observer, = self.create_groups(1)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT ALL ON collection_runs TO "{observer}"'))
            connection.execute(text(f'GRANT ALL ON collection_runs TO "{self.role}"'))
        self.provision()
        self.assert_restricted()
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            self.assertTrue(self.effective_privilege(observer, "collection_runs", privilege))

    def test_privileged_and_owning_identities_are_rejected_without_repurposing(self):
        candidate, = self.create_groups(1)
        for attribute in ("SUPERUSER", "CREATEDB", "CREATEROLE", "REPLICATION", "BYPASSRLS"):
            with self.subTest(attribute=attribute):
                with self.engine.begin() as connection:
                    connection.execute(text(f'ALTER ROLE "{candidate}" {attribute}'))
                try:
                    with self.engine.connect() as connection, self.assertRaises(ValueError):
                        assert_runtime_role(connection, role_name=candidate)
                    with self.assertRaises(SQLAlchemyError) as caught:
                        provision_runtime_role(Settings(_env_file=None), candidate, secrets.token_hex(32))
                    self.assertIn("Refusing to repurpose", str(caught.exception.orig))
                finally:
                    with self.engine.begin() as connection:
                        connection.execute(text(f'ALTER ROLE "{candidate}" NO{attribute}'))
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE public.permission_owner_probe (id integer)"))
            connection.execute(text(f'ALTER TABLE public.permission_owner_probe OWNER TO "{candidate}"'))
        try:
            with self.engine.connect() as connection, self.assertRaises(ValueError):
                assert_runtime_role(connection, role_name=candidate)
            with self.assertRaises(SQLAlchemyError) as caught:
                provision_runtime_role(Settings(_env_file=None), candidate, secrets.token_hex(32))
            self.assertIn("Refusing to repurpose", str(caught.exception.orig))
            with self.engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT pg_get_userbyid(relowner) FROM pg_class "
                    "WHERE oid = 'public.permission_owner_probe'::regclass")).scalar_one(), candidate)
        finally:
            with self.engine.begin() as connection:
                connection.execute(text("DROP TABLE public.permission_owner_probe"))
        self.assert_restricted()
