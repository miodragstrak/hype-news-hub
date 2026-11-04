from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import Settings
from app.selfhosted import create_selfhosted_app
from app.selfhosted_tools import provision_selfhosted_role
from tests.integration.test_persistent_collection import source, post
from tests.integration.auth_support import AuthDatabaseCase


class SelfhostedReadinessTests(AuthDatabaseCase):
    def config(self, **values):
        return self.runtime_config.model_copy(update=dict(app_env="production", backend_cors_origins="https://news.example.invalid",
            backend_cors_origin_regex=None, ai_processing_provider="disabled") | values)

    def provision(self):
        provision_selfhosted_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())

    def readiness(self, **values):
        with TestClient(create_selfhosted_app(self.config(**values))) as client:
            return client.get("/ready")

    def test_provisioning_is_repeatable_and_only_grants_marker_read_access(self):
        with self.engine.begin() as c:
            c.execute(text(f'REVOKE SELECT(version_num) ON public.alembic_version FROM "{self.role}"'))
        self.assertEqual(self.readiness().status_code, 503)  # No marker grant from legacy provisioning.
        self.provision()
        self.provision()
        self.assertEqual(self.readiness().status_code, 200)

        with self.repository.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one(), "20261104_07")
            connection.rollback()
            for sql in ["UPDATE public.alembic_version SET version_num=version_num", "DELETE FROM public.alembic_version", "TRUNCATE public.alembic_version"]:
                with self.assertRaises(ProgrammingError) as denied:
                    connection.execute(text(sql))
                self.assertEqual(denied.exception.orig.sqlstate, "42501")
                connection.rollback()
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)
        self.assertEqual(self.readiness().status_code, 200)

    def test_public_marker_write_grants_require_admin_review_and_are_not_silently_revoked(self):
        self.provision()
        try:
            with self.engine.begin() as c:
                c.execute(text("GRANT UPDATE(version_num) ON public.alembic_version TO PUBLIC"))
            self.assertEqual(self.readiness().status_code, 503)
            with self.assertRaisesRegex(ValueError, "administrator review"):
                self.provision()
            with self.engine.connect() as c:
                self.assertTrue(c.execute(text("SELECT pg_catalog.has_any_column_privilege(CAST(:role AS pg_catalog.name), 'public.alembic_version', 'UPDATE')"), {"role": self.role}).scalar_one())
        finally:
            with self.engine.begin() as c:
                c.execute(text("REVOKE UPDATE(version_num) ON public.alembic_version FROM PUBLIC"))
        self.provision()
        self.assertEqual(self.readiness().status_code, 200)

    def test_wrong_revision_and_missing_required_grants_fail_then_recover(self):
        self.provision()
        try:
            with self.engine.begin() as c:
                c.execute(text("UPDATE public.alembic_version SET version_num='20261101_05'"))
            self.assertEqual(self.readiness().status_code, 503)
        finally:
            with self.engine.begin() as c:
                c.execute(text("UPDATE public.alembic_version SET version_num='20261104_07'"))
        with self.engine.begin() as c:
            c.execute(text(f'REVOKE INSERT ON public.ai_processing_runs FROM "{self.role}"'))
        self.assertEqual(self.readiness().status_code, 503)
        self.provision()
        self.assertEqual(self.readiness().status_code, 200)

    def test_owner_and_column_permission_drift_are_rejected(self):
        self.provision()
        owner = Settings(_env_file=None)
        self.assertEqual(self.readiness(postgres_user=owner.postgres_user, postgres_password=owner.postgres_password).status_code, 503)
        with self.engine.begin() as c:
            c.execute(text(f'GRANT UPDATE(version_num) ON public.alembic_version TO "{self.role}"'))
        self.assertEqual(self.readiness().status_code, 503)
        self.provision()
        self.assertEqual(self.readiness().status_code, 200)

    def test_missing_required_column_is_not_hidden_by_a_correct_revision_marker(self):
        self.provision()
        try:
            with self.engine.begin() as c:
                c.execute(text("ALTER TABLE public.stories RENAME COLUMN headline TO missing_headline"))
            self.assertEqual(self.readiness().status_code, 503)
        finally:
            with self.engine.begin() as c:
                c.execute(text("ALTER TABLE public.stories RENAME COLUMN missing_headline TO headline"))
        self.assertEqual(self.readiness().status_code, 200)
