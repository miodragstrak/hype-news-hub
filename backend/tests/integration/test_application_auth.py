from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from unittest.mock import patch

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from app.bootstrap_admin import bootstrap_admin
from app.core.config import Settings
from app.models.auth import User, LoginSession
from app.selfhosted import create_selfhosted_app
from app.selfhosted_tools import provision_selfhosted_role
from app.services.authentication import COOKIE
from tests.integration.auth_support import AuthDatabaseCase
from tests.integration.test_postgresql import alembic_config
from tests.integration.test_persistent_collection import PersistentCollectionCase, source, post
from uuid import uuid4

ORIGIN = "https://news.example.invalid"


class ApplicationAuthenticationTests(AuthDatabaseCase):
    def setUp(self):
        super().setUp()
        self.owner = Settings(_env_file=None)
        provision_selfhosted_role(self.owner, self.role, self.runtime_config.postgres_password.get_secret_value())
        self.password = secrets.token_urlsafe(24)
        bootstrap_admin(self.owner, "ADMIN@example.invalid", self.password)
        self.config = self.runtime_config.model_copy(update={"app_env": "production", "backend_cors_origins": ORIGIN,
            "backend_cors_origin_regex": None, "auth_enabled": True, "auth_trusted_proxy_ips": "10.42.0.1"})
        self.web = self.browser()
        self.addCleanup(self.web.close)

    def browser(self, peer="198.51.100.23"):
        app = create_selfhosted_app(self.config)
        client = TestClient(app, base_url=ORIGIN, client=(peer, 1234))
        self.addCleanup(lambda: app.state.news_repository.engine.dispose() if "engine" in app.state.news_repository.__dict__ else None)
        return client

    def login(self, client=None, email="admin@example.invalid", password=None, **headers):
        return (client or self.web).post("/api/auth/login", json={"email": email, "password": password or self.password}, headers={"Origin": ORIGIN, **headers})

    def csrf(self, client=None):
        return {"Origin": ORIGIN, "X-CSRF-Token": (client or self.web).get("/api/auth/session").json()["csrf_token"]}

    def create(self, email="editor@example.invalid", role="editor"):
        return self.web.post("/api/admin/users", json={"email": email, "password": self.password, "role": role}, headers=self.csrf())

    def change(self, user, **values):
        return self.web.patch("/api/admin/users/" + user["id"], json={"expected_revision": user["revision"],
            "role": user["role"], "active": user["active"], **values}, headers=self.csrf())

    def test_cookie_flags_hashed_storage_and_restart_session_bootstrap(self):
        result = self.login()
        self.assertEqual(result.status_code, 200)
        flags = result.headers["set-cookie"].lower()
        for flag in ["secure", "httponly", "samesite=lax", "path=/"]:
            self.assertIn(flag, flags)
        self.assertNotIn("domain=", flags)
        token = self.web.cookies.get(COOKIE)
        self.assertNotIn(token, result.text)
        with self.factory() as s:
            row = s.scalar(select(LoginSession))
            self.assertEqual(row.token_hash, hashlib.sha256(token.encode()).hexdigest())
            self.assertNotEqual(row.token_hash, token)
            self.assertTrue(s.scalar(select(User.password_hash)).startswith("$argon2id$"))
        other = self.browser()
        try:
            other.cookies.update(self.web.cookies)
            self.assertEqual(other.get("/api/auth/session").status_code, 200)
            self.assertEqual(other.get("/api/editorial/capabilities").json()["roles"], ["administrator"])
        finally:
            other.close()

    def test_generic_errors_for_unknown_wrong_and_inactive_accounts(self):
        wrong = self.login(password=secrets.token_urlsafe(24))
        unknown = self.login(email="missing@example.invalid")
        self.login()
        user = self.create().json()
        self.assertEqual(self.change(user, active=False).status_code, 200)
        inactive = self.login(email="editor@example.invalid")
        self.assertEqual([r.status_code for r in [wrong, unknown, inactive]], [401]*3)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json(), inactive.json())

    def test_all_existing_routes_are_authenticated_and_demo_generation_disabled(self):
        for route in self.web.app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/api/") and not path.startswith("/api/auth/"):
                self.assertEqual(self.web.get(path).status_code, 401, path)
        self.assertEqual(self.web.get("/docs").status_code, 401)
        self.login()
        self.assertEqual(self.web.get("/api/stories").status_code, 200)
        self.assertEqual(self.web.get("/api/editorial-queue").status_code, 200)
        self.assertEqual(self.web.post("/api/editorial-stories/example/generate-demo-draft", headers=self.csrf()).status_code, 403)
        self.assertEqual(self.web.get("/ready").status_code, 200)

    def test_csrf_and_login_origin_rejection_have_no_sessions_or_editorial_writes(self):
        self.assertEqual(self.login(Origin="https://attacker.invalid").status_code, 403)
        with self.factory() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(LoginSession)), 0)
        self.login()
        self.assertEqual(self.web.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.web.get("/api/collect").status_code, 403)
        self.assertEqual(self.web.post("/api/admin/users", json={}, headers={"Origin": ORIGIN,"X-CSRF-Token":"wrong"}).status_code,403)
        self.assertEqual(self.web.get("/api/auth/session").status_code,200)

    def test_editor_restrictions_and_current_role_changes(self):
        self.login()
        user = self.create().json()
        editor = self.browser()
        try:
            self.assertEqual(self.login(editor,email=user["email"]).status_code,200)
            capabilities=editor.get("/api/editorial/capabilities").json()
            self.assertIn("editorial:edit",capabilities["permissions"])
            self.assertNotIn("editorial:review",capabilities["permissions"])
            self.assertEqual(editor.get("/api/admin/users").status_code,403)
            self.assertEqual(editor.post("/api/admin/users",json={},headers=self.csrf(editor)).status_code,403)
            self.assertEqual(self.change(user,role="admin").status_code,200)
            self.assertEqual(editor.get("/api/admin/users").status_code,200)
            user=self.web.get("/api/admin/users").json()
            changed=next(u for u in user if u["email"]=="editor@example.invalid")
            self.assertEqual(self.change(changed,role="editor").status_code,200)
            self.assertEqual(editor.get("/api/admin/users").status_code,403)
        finally:editor.close()

    def test_expiration_logout_cookie_deletion_and_deactivation_revoke_sessions(self):
        self.login()
        headers=self.csrf()
        response=self.web.post("/api/auth/logout",headers=headers)
        self.assertEqual(response.status_code,204)
        self.assertIn("max-age=0",response.headers["set-cookie"].lower())
        self.assertEqual(self.web.get("/api/auth/session").status_code,401)
        self.login()
        with self.engine.begin() as c:
            c.execute(update(LoginSession).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        self.assertEqual(self.web.get("/api/auth/session").status_code,401)
        self.login()
        user=self.create().json()
        editor=self.browser()
        try:
            self.login(editor,email=user["email"])
            self.assertEqual(self.change(user,active=False).status_code,200)
            self.assertEqual(editor.get("/api/stories").status_code,401)
            with self.factory() as s:
                self.assertTrue(all(row.revoked_at for row in s.scalars(select(LoginSession).where(LoginSession.user_id==user["id"]))))
        finally:editor.close()

    def test_last_admin_and_bootstrap_guards(self):
        with self.assertRaises(ValueError):bootstrap_admin(self.owner,"another@example.invalid",self.password)
        self.login()
        user=self.web.get("/api/auth/session").json()["user"]
        self.assertEqual(self.change(user,role="editor").status_code,409)
        self.assertEqual(self.change(user,active=False).status_code,409)
        self.assertEqual(self.create(email=" Admin@EXAMPLE.invalid ").status_code,409)
        self.assertNotIn("password_hash",self.web.get("/api/admin/users").text)

    def test_concurrent_last_admin_demotion_serializes_across_instances(self):
        self.login()
        first=self.web.get("/api/auth/session").json()["user"]
        second=self.create(email="second@example.invalid",role="admin").json()
        other=self.browser()
        try:
            self.login(other,email=second["email"])
            headers=[self.csrf(),self.csrf(other)]
            def demote(item):
                client,user,h=item
                return client.patch('/api/admin/users/'+user['id'],json=dict(expected_revision=1,role='editor',active=True),headers=h).status_code
            with ThreadPoolExecutor(2) as pool:
                codes=list(pool.map(demote,[(self.web,first,headers[0]),(other,second,headers[1])]))
            self.assertEqual(sorted(codes),[200,409])
        finally:other.close()

    def test_rate_limit_shared_between_instances_and_untrusted_forwarded_headers_ignored(self):
        other=self.browser()
        try:
            for i in range(10):
                client=self.web if i%2 else other
                self.assertEqual(self.login(client,email=f'unknown{i}@example.invalid',**{'X-Forwarded-For':f'198.51.100.{i+1}'}).status_code,401)
            self.assertEqual(self.login(other,email='another@example.invalid').status_code,429)
        finally:other.close()

    def test_trusted_nginx_real_ip_is_used_and_missing_header_fails_closed(self):
        proxy=self.browser('10.42.0.1')
        try:
            self.assertEqual(self.login(proxy).status_code,503)
            self.assertEqual(self.login(proxy,**{'X-Real-IP':'203.0.113.17'}).status_code,200)
        finally:proxy.close()

    def test_forward_only_migration_refuses_downgrade_and_metadata_matches(self):
        with self.engine.begin() as c:
            cfg=alembic_config(c,include_auth=True)
            command.check(cfg)
        with self.assertRaisesRegex(RuntimeError,'forward-only'),self.engine.begin() as c:
            command.downgrade(alembic_config(c,include_auth=True),'20261101_06')

    def test_cookie_editor_draft_submission_and_separate_admin_review(self):
        story=self.collect([source(posts=[post()])]).json()['stories'][0]['id']
        self.login();user=self.create().json();editor=self.browser()
        try:
            self.login(editor,email=user['email'])
            src=editor.get(f'/api/editorial/stories/{story}/sources').json()[0]
            payload=dict(headline='Urednički pregled događaja',body='Urednički potvrđen tekst iz izvora.',excerpt='Sažetak izvora.',
                slug='urednicki-pregled',categories=['Kultura'],tags=[],seo=dict(title='Urednički pregled',description='Sažetak događaja.'),images=[],
                source_attribution=[dict(article_id=src['article_id'],source_id=src['source_id'])])
            made=editor.post('/api/editorial/drafts',json=dict(command_id=str(uuid4()),story_id=story,expected_revision=0,target_locale='sr-Latn',payload=payload),headers=self.csrf(editor))
            self.assertEqual(made.status_code,201,made.text);receipt=made.json();draft=receipt['draft_id']
            command_body=dict(command_id=str(uuid4()),expected_revision=1,version_number=receipt['version_number'],content_hash=receipt['content_hash'])
            submitted=editor.post(f'/api/editorial/drafts/{draft}/submit',json=command_body,headers=self.csrf(editor))
            self.assertEqual(submitted.status_code,200,submitted.text)
            decision=dict(command_id=str(uuid4()),expected_revision=2,version_number=receipt['version_number'],content_hash=receipt['content_hash'],reason='Odvojena urednička provera.')
            self.assertEqual(editor.post(f'/api/editorial/drafts/{draft}/approve',json=decision,headers=self.csrf(editor)).status_code,403)
            approved=self.web.post(f'/api/editorial/drafts/{draft}/approve',json=decision,headers=self.csrf())
            self.assertEqual(approved.status_code,200,approved.text)
            result=self.web.get(f'/api/editorial/drafts/{draft}').json()
            self.assertTrue(result['effective_approval']);self.assertEqual(result['current_version']['content_hash'],receipt['content_hash'])
        finally:editor.close()

    def test_concurrent_bootstrap_creates_exactly_one_initial_admin(self):
        with self.engine.begin() as c:c.execute(text("TRUNCATE public.app_security_events, public.app_users CASCADE"))
        def create(email):
            try:bootstrap_admin(self.owner,email,self.password);return 'created'
            except ValueError:return 'refused'
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(create,['first@example.invalid','second@example.invalid'])),['created','refused'])
        with self.factory() as s:self.assertEqual(s.scalar(select(func.count()).select_from(User)),1)


class ApplicationAuthPopulatedMigrationTests(PersistentCollectionCase):
    def test_upgrade_populated_revision_06_preserves_collection_and_recollection(self):
        from app.database.base import Base
        from app.models.auth import AuthBase
        from app.models import CollectedArticle

        first = self.collect([source(posts=[post()])])
        self.assertEqual(first.status_code, 200, first.text)
        story = first.json()["stories"][0]["id"]

        def snapshot(connection):
            return {table.name: sorted(str(row[0]) for row in connection.execute(
                text(f'SELECT pg_catalog.to_jsonb(t) FROM public."{table.name}" t')))
                for table in Base.metadata.sorted_tables}

        with self.engine.begin() as connection:
            before = snapshot(connection)
            command.upgrade(alembic_config(connection, include_auth=True), "20261104_08")
        try:
            with self.engine.begin() as connection:
                self.assertEqual(snapshot(connection), before)
                command.check(alembic_config(connection, include_auth=True))
            owner = Settings(_env_file=None)
            provision_selfhosted_role(owner, self.role, self.runtime_config.postgres_password.get_secret_value())
            repeated = self.collect([source(posts=[post()])])
            self.assertEqual(repeated.status_code, 200, repeated.text)
            self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")
            self.assertEqual(repeated.json()["stories"][0]["id"], story)
            self.assertEqual(self.count(CollectedArticle), 1)
        finally:
            # Only this fixture's initially-empty disposable database is cleaned.
            with self.engine.begin() as connection:
                self.assertEqual(connection.scalar(text("SELECT current_database()")), "hype_news_hub_test")
                AuthBase.metadata.drop_all(connection)
                connection.execute(text("DROP FUNCTION IF EXISTS public.hwn_security_event_immutable()"))
                command.stamp(alembic_config(connection, include_auth=True), "20261101_06")
