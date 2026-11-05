from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import multiprocessing
import secrets
from uuid import uuid4
from unittest.mock import patch

from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError, IntegrityError

from app.bootstrap_admin import bootstrap_admin
from app.core.config import Settings
from app.models.auth import User, LoginSession, LoginThrottle, SecurityEvent, AuthBase
from app.repositories.news_repository import PostgresNewsRepository, StorageUnavailable
from app.services.authentication import Authentication, AuthError, AUTH_POLICY
from app.selfhosted_tools import provision_selfhosted_role
from tests.integration.auth_support import AuthDatabaseCase
from tests.integration.test_persistent_collection import PersistentCollectionCase, source, post
from tests.integration.test_postgresql import alembic_config


def process_throttle(config, address, emails, barrier, queue):
    repository = PostgresNewsRepository(config)
    try:
        service = Authentication(repository)
        barrier.wait(timeout=15)
        codes = []
        for email in emails:
            try:
                service.throttle(email, address)
                codes.append(200)
            except AuthError as exc:
                codes.append(exc.status)
        queue.put(codes)
    finally:
        if "engine" in repository.__dict__:
            repository.engine.dispose()


def distinct_emails(count):
    values, buckets = [], set()
    for i in range(count * 10):
        email = f"account{i}@example.invalid"
        bucket = int(hashlib.sha256(email.encode()).hexdigest(), 16) % 4096
        if bucket not in buckets:
            buckets.add(bucket)
            values.append(email)
        if len(values) == count:
            return values
    raise AssertionError("Could not prepare distinct throttle buckets")


class AccountHardeningTests(AuthDatabaseCase):
    def setUp(self):
        super().setUp()
        self.owner = Settings(_env_file=None)
        provision_selfhosted_role(self.owner, self.role, self.runtime_config.postgres_password.get_secret_value())
        self.password = secrets.token_urlsafe(24)
        bootstrap_admin(self.owner, "admin@example.invalid", self.password)
        self.service = Authentication(self.repository)
        self.context = self.service.resolve(self.service.login("admin@example.invalid", self.password, "198.51.100.1"))
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE public.app_login_throttles"))

    def test_blocked_ip_and_account_cannot_spend_global_capacity(self):
        emails = distinct_emails(50)
        for email in emails[:10]:
            self.service.throttle(email, "198.51.100.10")
        for email in emails[10:]:
            with self.assertRaises(AuthError) as error:
                self.service.throttle(email, "198.51.100.10")
            self.assertEqual(error.exception.status, 429)
        with self.factory() as session:
            self.assertEqual(session.get(LoginThrottle, 0).attempts, 10)
        self.service.throttle("unrelated@example.invalid", "203.0.113.99")
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE public.app_login_throttles"))
        for i in range(5):
            self.service.throttle("blocked@example.invalid", f"198.51.100.{i+1}")
        for i in range(20):
            with self.assertRaises(AuthError):
                self.service.throttle("blocked@example.invalid", f"203.0.113.{i+1}")
        with self.factory() as session:
            self.assertEqual(session.get(LoginThrottle, 0).attempts, 5)
        self.service.throttle("unrelated@example.invalid", "192.0.2.100")

    def test_independent_processes_share_atomic_limits_without_charging_blocked_attempts(self):
        ctx = multiprocessing.get_context("spawn")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        emails = distinct_emails(50)
        processes = [ctx.Process(target=process_throttle, args=(self.runtime_config, address, items, barrier, queue))
                     for address, items in [("198.51.100.10", emails[:20]), ("203.0.113.99", emails[20:40])]]
        try:
            for process in processes: process.start()
            results = [queue.get(timeout=30) for _ in processes]
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            for result in results:
                self.assertEqual(Counter(result), {200: 10, 429: 10})
            with self.factory() as session:
                self.assertEqual(session.get(LoginThrottle, 0).attempts, 20)
            for email in emails[40:]: self.service.throttle(email, "192.0.2.100")
            with self.assertRaises(AuthError): self.service.throttle("last@example.invalid", "192.0.2.101")
            with self.factory() as session: self.assertEqual(session.get(LoginThrottle, 0).attempts, 30)
        finally:
            for process in processes:
                if process.is_alive(): process.terminate()
                if process.pid is not None: process.join(timeout=5)
            queue.close()

    def test_process_races_cannot_overspend_account_or_global_budget(self):
        emails = distinct_emails(40)
        cases = [
            ([("198.51.100.10", ["same@example.invalid"]*10), ("203.0.113.99", ["same@example.invalid"]*10)], 5),
            ([("198.51.100.10", emails[:10]), ("203.0.113.99", emails[10:20]),
              ("192.0.2.100", emails[20:30]), ("192.0.2.101", emails[30:])], 30),
        ]
        for items, admitted in cases:
            with self.engine.begin() as connection: connection.execute(text("TRUNCATE public.app_login_throttles"))
            ctx = multiprocessing.get_context("spawn")
            barrier, queue = ctx.Barrier(len(items)), ctx.Queue()
            processes = [ctx.Process(target=process_throttle, args=(self.runtime_config, address, addresses, barrier, queue)) for address, addresses in items]
            try:
                for process in processes: process.start()
                results = [queue.get(timeout=30) for _ in processes]
                for process in processes:
                    process.join(timeout=10)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual(sum(result.count(200) for result in results), admitted)
                with self.factory() as session: self.assertEqual(session.get(LoginThrottle, 0).attempts, admitted)
            finally:
                for process in processes:
                    if process.is_alive(): process.terminate()
                    if process.pid is not None: process.join(timeout=5)
                queue.close()

    def test_account_events_have_verified_attribution_and_survive_new_application_service(self):
        user = self.service.create_user(self.context, "editor@example.invalid", self.password, "editor")
        user = self.service.update_user(self.context, user["id"], user["revision"], "admin", True)
        user = self.service.update_user(self.context, user["id"], user["revision"], "admin", False)
        user = self.service.update_user(self.context, user["id"], user["revision"], "editor", True)
        restarted = Authentication(PostgresNewsRepository(self.runtime_config))
        try:
            self.assertEqual(restarted.resolve(self.service.login("admin@example.invalid", self.password, "198.51.100.1")).account["role"], "admin")
            with restarted.transaction() as session:
                events = list(session.scalars(select(SecurityEvent).order_by(SecurityEvent.occurred_at)))
                self.assertEqual(Counter(e.action for e in events), {"user.created": 2, "user.role_changed": 2, "user.deactivated": 1, "user.activated": 1})
                for event in events[1:]:
                    self.assertEqual(event.actor_subject, self.context.principal.subject)
                    self.assertEqual(str(event.actor_user_id), self.context.principal.subject)
                    self.assertEqual(event.actor_issuer, self.context.principal.issuer)
                    self.assertEqual(event.target_user_id, user["id"])
                    self.assertEqual(event.outcome, "success")
                    self.assertIsNotNone(event.occurred_at.tzinfo)
                self.assertEqual(events[0].actor_issuer, "urn:hype-world-news:bootstrap")
                serialized = str([e.__dict__ for e in events])
                for secret in [self.password, self.context.token_hash, self.context.csrf]: self.assertNotIn(secret, serialized)
        finally: restarted.repository.engine.dispose()

    def test_rejected_last_admin_edit_is_recorded_and_account_is_unchanged(self):
        user = self.context.account
        with self.assertRaises(AuthError): self.service.update_user(self.context, user["id"], user["revision"], "editor", False)
        with self.factory() as session:
            event = session.scalar(select(SecurityEvent).where(SecurityEvent.action == "user.update_rejected"))
            self.assertEqual(event.outcome, "conflict")
            account = session.get(User, user["id"])
            self.assertEqual((account.role, account.active, account.revision), ("admin", True, 1))

    def test_audit_insert_failure_rolls_back_account_creation(self):
        with patch("app.services.authentication.record_user_event", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError): self.service.create_user(self.context, "rollback@example.invalid", self.password, "editor")
        with self.factory() as session:
            self.assertIsNone(session.scalar(select(User).where(User.email == "rollback@example.invalid")))
            self.assertEqual(session.scalar(select(func.count()).select_from(SecurityEvent)), 1)

    def test_runtime_cannot_change_history_and_drift_is_rejected(self):
        for sql in ["DELETE FROM public.app_security_events", "UPDATE public.app_security_events SET outcome='denied'", "TRUNCATE public.app_security_events"]:
            with self.repository.engine.connect() as connection:
                with self.assertRaises(ProgrammingError) as error: connection.execute(text(sql))
                self.assertEqual(error.exception.orig.sqlstate, "42501")
        with self.assertRaises(IntegrityError) as error, self.engine.begin() as connection:
            connection.execute(text("UPDATE public.app_security_events SET outcome='denied'"))
        self.assertEqual(error.exception.orig.sqlstate, "23514")
        try:
            with self.engine.begin() as connection: connection.execute(text(f'GRANT UPDATE ON public.app_security_events TO "{self.role}"'))
            with self.assertRaises(StorageUnavailable): self.service.resolve("a"*43)
        finally: provision_selfhosted_role(self.owner, self.role, self.runtime_config.postgres_password.get_secret_value())

    def test_owner_retention_batch_keeps_active_and_recent_sessions(self):
        now = datetime.now(timezone.utc)
        user = self.context.account["id"]
        with self.engine.begin() as connection:
            for key, expiry, revocation in [
                ("1", now-timedelta(days=40), None),
                ("2", now+timedelta(days=1), now-timedelta(days=40)),
                ("3", now-timedelta(days=1), None),
                ("4", now+timedelta(days=1), None),
                ("5", now+timedelta(days=1), now-timedelta(days=1)),
            ]:
                connection.execute(LoginSession.__table__.insert().values(token_hash=key*64, user_id=user, expires_at=expiry, revoked_at=revocation))
            removed = connection.execute(text("""WITH batch AS (
                SELECT token_hash FROM public.app_sessions
                WHERE expires_at < clock_timestamp() - make_interval(days => :days)
                   OR revoked_at < clock_timestamp() - make_interval(days => :days)
                ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED
            ) DELETE FROM public.app_sessions s USING batch b
              WHERE s.token_hash=b.token_hash RETURNING s.token_hash"""), {"days": 30}).scalars().all()
            self.assertEqual(set(removed), {"1"*64, "2"*64})
        with self.factory() as session:
            self.assertIsNotNone(session.get(LoginSession, self.context.token_hash))
            self.assertEqual(session.scalar(select(func.count()).select_from(SecurityEvent)), 1)


class SecurityEventMigrationTests(PersistentCollectionCase):
    def test_populated_07_upgrade_preserves_accounts_sessions_and_collection(self):
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)
        user_id = uuid4()
        with self.engine.begin() as connection:
            config = alembic_config(connection, include_auth=True)
            command.upgrade(config, "20261104_07")
            connection.execute(User.__table__.insert().values(id=user_id, email="legacy@example.invalid", password_hash="not-a-credential", role="admin", active=True, revision=1))
            connection.execute(LoginSession.__table__.insert().values(token_hash="a"*64, user_id=user_id, expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
            before = connection.execute(text("SELECT pg_catalog.to_jsonb(u) FROM public.app_users u")).scalar_one()
            command.upgrade(config, "20261104_08")
        try:
            with self.engine.begin() as connection:
                self.assertEqual(connection.execute(text("SELECT pg_catalog.to_jsonb(u) FROM public.app_users u")).scalar_one(), before)
                self.assertEqual(connection.scalar(text("SELECT count(*) FROM public.app_sessions")), 1)
                self.assertEqual(connection.scalar(text("SELECT count(*) FROM public.collected_articles")), 1)
                self.assertEqual(connection.scalar(text("SELECT count(*) FROM public.app_security_events")), 0)
                command.check(alembic_config(connection, include_auth=True))
            with self.assertRaisesRegex(RuntimeError, "forward-only"), self.engine.begin() as connection:
                command.downgrade(alembic_config(connection, include_auth=True), "20261104_07")
        finally:
            with self.engine.begin() as connection:
                self.assertEqual(connection.scalar(text("SELECT current_database()")), "hype_news_hub_test")
                AuthBase.metadata.drop_all(connection)
                connection.execute(text("DROP FUNCTION public.hwn_security_event_immutable()"))
                command.stamp(alembic_config(connection, include_auth=True), "20261101_06")
