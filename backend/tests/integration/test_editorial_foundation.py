"""Database-specific checks; inherited fixture refuses non-disposable databases."""
from uuid import uuid4

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import Settings
from app.database.runtime_security import EDITORIAL_HISTORY_TABLES, RUNTIME_TABLES, provision_runtime_role
from app.database.session import create_database_engine, create_session_factory
from app.main import create_app
from app.models import (
    CollectedArticle, EditorialDecision, EditorialDraft, EditorialDraftVersion, EditorialEvent,
    EditorialVersionSource, NewsSource, Story,
)
from editorial_identity import TestIdentityVerifier
from integration.test_persistent_collection import PersistentCollectionCase, post, source
from tests.integration.test_postgresql import alembic_config

ACTOR = {"actor_issuer": "urn:hnh:test", "actor_subject": "fixture-editor"}
PRIVATE = "PRIVATE EDITORIAL CONTENT NEVER EXPOSED BY LEGACY ROUTES"
EDITORIAL_TABLES = ("editorial_drafts", *EDITORIAL_HISTORY_TABLES)


class EditorialFoundationTests(PersistentCollectionCase):
    def tearDown(self):
        # Owner maintenance of the explicitly isolated, initially empty test DB.
        # No CASCADE: collection records are handled by the existing fixture.
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE " + ", ".join("public." + table for table in
                ("ai_processing_events", "ai_processing_runs", *EDITORIAL_TABLES))))
        super().tearDown()

    def source_snapshot(self, draft_id, version_number, article, **overrides):
        values = dict(draft_id=draft_id, version_number=version_number, source_id=article.source_id,
                      article_id=article.id, source_name=article.source.name, source_url=article.source.url,
                      external_id=article.external_id, original_url=article.url, canonical_url=article.canonical_url,
                      published_at=article.published_at, input_text=article.title + "\n\n" + (article.content or ""))
        return EditorialVersionSource(**(values | overrides))

    def seed(self, factory=None, collect=True, with_decision=True):
        if collect:
            response = self.collect([source(posts=[post(content="Tačan izvorni tekst.\n\nDrugi pasus: čćšžđ.")])])
            self.assertEqual(response.status_code, 200, response.text)
        with (factory or self.factory).begin() as session:
            article = session.scalars(select(CollectedArticle)).first()
            story_id = session.scalar(select(Story.id))
            draft = EditorialDraft(story_id=story_id, **ACTOR)
            session.add(draft)
            session.flush()
            version = EditorialDraftVersion(draft_id=draft.id, version_number=1,
                payload={"headline": PRIVATE, "content": "Srpski urednički tekst."}, source_count=1, **ACTOR)
            session.add(version)
            session.flush()
            snapshot = self.source_snapshot(draft.id, 1, article)
            session.add(snapshot)
            session.flush()
            decision = EditorialDecision(draft_id=draft.id, version_number=1, content_hash=version.content_hash,
                                         decision="approve", actor_issuer="urn:hnh:test", actor_subject="fixture-reviewer")
            event = EditorialEvent(draft_id=draft.id, version_number=1, event_type="foundation.seeded",
                                   to_status="editing", command_id=uuid4(), request_hash="a" * 64, **ACTOR)
            session.add(event)
            if with_decision:
                session.add(decision)
            draft.current_version_number = 1
            session.flush()
            return dict(draft_id=draft.id, version_id=version.id, snapshot_id=snapshot.id, decision_id=decision.id,
                        event_id=event.id, content_hash=version.content_hash, snapshot_hash=snapshot.snapshot_hash,
                        input_text=snapshot.input_text, article_id=article.id, source_id=article.source_id, story_id=story_id,
                        revision=draft.revision)

    def collection_snapshot(self):
        with self.engine.connect() as connection:
            return {table: connection.execute(text(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]'::jsonb) FROM public.{table} t"
            )).scalar_one() for table in RUNTIME_TABLES}

    def test_runtime_can_create_complete_foundation_and_read_private_capabilities(self):
        values = self.seed(factory=create_session_factory(self.repository.engine))
        with self.factory() as session:
            self.assertEqual(session.get(EditorialDraft, values["draft_id"]).revision, 2)
            self.assertEqual(session.get(EditorialDraftVersion, values["version_id"]).content_hash, values["content_hash"])
        application = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(application) as client:
                response = client.get("/api/editorial/capabilities", headers={"Authorization": "Bearer fixture-reader"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["commands_enabled"], False)
                self.assertNotIn(PRIVATE, response.text)
        finally:
            application.state.news_repository.engine.dispose()

    def test_frozen_provenance_survives_recollection_and_new_connections(self):
        values = self.seed()
        self.collect([source(posts=[post(title="Changed upstream headline", content="Changed upstream body")])])
        fresh_engine = create_database_engine(self.runtime_config)
        try:
            with create_session_factory(fresh_engine)() as session:
                snapshot = session.get(EditorialVersionSource, values["snapshot_id"])
                self.assertEqual(snapshot.input_text, values["input_text"])
                self.assertEqual(snapshot.snapshot_hash, values["snapshot_hash"])
                self.assertEqual((snapshot.article_id, snapshot.source_id), (values["article_id"], values["source_id"]))
                self.assertTrue(snapshot.original_url and snapshot.canonical_url and snapshot.published_at and snapshot.captured_at)
                self.assertNotEqual(session.get(CollectedArticle, values["article_id"]).content, snapshot.input_text)
                self.assertEqual(session.get(EditorialDraftVersion, values["version_id"]).payload["headline"], PRIVATE)
                self.assertEqual(session.get(EditorialDecision, values["decision_id"]).content_hash, values["content_hash"])
        finally:
            fresh_engine.dispose()

    def test_editorial_inserts_do_not_modify_collection_history(self):
        self.collect([source(posts=[post()])])
        before = self.collection_snapshot()
        self.seed(collect=False)
        self.assertEqual(self.collection_snapshot(), before)

    def test_private_content_is_not_projected_into_public_legacy_routes(self):
        values = self.seed()
        for path in ("/api/stories", "/api/editorial-queue", f"/api/editorial-stories/{values['story_id']}"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(PRIVATE, response.text)
        workspace = self.client.get(f"/api/editorial-stories/{values['story_id']}").json()
        self.assertEqual(workspace["serbian_draft"]["status"], "not_generated")
        self.assertEqual(self.client.get("/api/editorial/capabilities").status_code, 401)

    def test_history_cannot_be_updated_or_deleted_even_by_accidental_owner_dml(self):
        self.seed()
        for table in EDITORIAL_HISTORY_TABLES:
            for statement in (f"UPDATE public.{table} SET id = id", f"DELETE FROM public.{table}"):
                with self.subTest(statement=statement), self.assertRaises(IntegrityError):
                    with self.engine.begin() as connection:
                        connection.execute(text(statement))

    def test_runtime_history_permissions_and_ddl_are_restricted(self):
        self.seed(factory=create_session_factory(self.repository.engine))
        with self.repository.engine.connect() as connection:
            for table in EDITORIAL_TABLES:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    allowed = privilege in ("SELECT", "INSERT") or (table == "editorial_drafts" and privilege == "UPDATE")
                    actual = connection.execute(text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                                                {"table": "public." + table, "privilege": privilege}).scalar_one()
                    self.assertEqual(actual, allowed, (table, privilege))
        for statement in (
            "UPDATE editorial_draft_versions SET payload = '{}'::jsonb", "DELETE FROM editorial_events",
            "DELETE FROM editorial_drafts", "TRUNCATE editorial_version_sources", "TRUNCATE editorial_drafts CASCADE",
            "ALTER TABLE editorial_draft_versions DISABLE TRIGGER ALL", "ALTER TABLE editorial_drafts ADD COLUMN forbidden text",
            "CREATE TABLE forbidden_editorial (id integer)", "DROP TABLE editorial_events", "SELECT * FROM alembic_version",
        ):
            with self.subTest(statement=statement), self.assertRaises(SQLAlchemyError):
                with self.repository.engine.begin() as connection:
                    connection.execute(text(statement))

    def test_reprovisioning_requires_review_of_public_editorial_grants(self):
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT ALL ON TABLE editorial_events, editorial_drafts TO "{self.role}"'))
            connection.execute(text("GRANT UPDATE ON TABLE editorial_draft_versions TO PUBLIC"))
        try:
            with self.assertRaisesRegex(ValueError, "PUBLIC grants.*administrator review"):
                provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
            with self.repository.engine.connect() as connection:
                self.assertTrue(connection.execute(text("SELECT has_table_privilege(current_user, 'editorial_draft_versions', 'UPDATE')")).scalar_one())
        finally:
            # Only an administrator may evaluate/remediate shared PUBLIC access.
            with self.engine.begin() as connection:
                connection.execute(text("REVOKE UPDATE ON TABLE editorial_draft_versions FROM PUBLIC"))
            provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
        with self.repository.engine.connect() as connection:
            for table, privilege in (("editorial_events", "UPDATE"), ("editorial_drafts", "DELETE"),
                                     ("editorial_draft_versions", "UPDATE")):
                self.assertFalse(connection.execute(text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                                                    {"table": table, "privilege": privilege}).scalar_one())

    def test_incomplete_versions_rollback_at_commit_with_head_unchanged(self):
        values = self.seed()
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.add(EditorialDraftVersion(draft_id=values["draft_id"], version_number=2,
                                                 payload={"content": "Incomplete"}, source_count=1, **ACTOR))
                draft = session.get(EditorialDraft, values["draft_id"])
                draft.current_version_number = 2
        with self.factory() as session:
            draft = session.get(EditorialDraft, values["draft_id"])
            self.assertEqual((draft.current_version_number, draft.revision), (1, values["revision"]))
            self.assertEqual(session.scalar(select(func.count()).select_from(EditorialDraftVersion)), 1)

    def test_later_source_insertion_cannot_change_a_sealed_version(self):
        values = self.seed()
        with self.factory.begin() as session:
            extra = CollectedArticle(source_id=values["source_id"], url="https://source.invalid/extra", title="Extra", content="Extra")
            session.add(extra)
            session.flush()
            extra_id = extra.id
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.add(self.source_snapshot(values["draft_id"], 1, session.get(CollectedArticle, extra_id)))
        self.assertEqual(self.count(EditorialVersionSource), 1)

    def test_cross_source_uuid_attribution_is_rejected(self):
        values = self.seed()
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                other = NewsSource(name="Other", url="https://other.invalid")
                session.add(other)
                session.flush()
                session.add(EditorialDraftVersion(draft_id=values["draft_id"], version_number=2,
                                                 payload={}, source_count=1, **ACTOR))
                session.flush()
                article = session.get(CollectedArticle, values["article_id"])
                session.add(self.source_snapshot(values["draft_id"], 2, article, source_id=other.id))

    def test_unique_locale_version_and_required_fields(self):
        values = self.seed()
        cases = (
            (EditorialDraft, dict(story_id=values["story_id"], **ACTOR)),
            (EditorialDraft, dict(story_id=values["story_id"], target_locale="sr-Cyrl", **ACTOR)),
            (EditorialDraftVersion, dict(draft_id=values["draft_id"], version_number=1, payload={}, source_count=1, **ACTOR)),
            (EditorialDraftVersion, dict(draft_id=values["draft_id"], version_number=2, payload=[], source_count=1, **ACTOR)),
            (EditorialDraftVersion, dict(draft_id=values["draft_id"], version_number=2, payload={}, source_count=0, **ACTOR)),
            (EditorialDraftVersion, dict(draft_id=values["draft_id"], version_number=2, payload={}, source_count=1, origin="demo", **ACTOR)),
            (EditorialDraftVersion, dict(draft_id=values["draft_id"], version_number=2, payload={}, source_count=1,
                                        actor_issuer="", actor_subject="someone")),
        )
        for model, fields in cases:
            with self.subTest(model=model.__name__, fields=fields), self.assertRaises(IntegrityError):
                with self.factory.begin() as session:
                    session.add(model(**fields))
                    session.flush()

    def test_draft_head_cannot_reference_another_drafts_version(self):
        self.seed()
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                story = Story(headline="Unrelated story")
                session.add(story)
                session.flush()
                session.add(EditorialDraft(story_id=story.id, current_version_number=1, **ACTOR))

    def test_decisions_require_exact_version_hash_and_negative_reason(self):
        values = self.seed()
        for fields in ({"content_hash": "b" * 64}, {"version_number": 99}, {"decision": "reject"},
                       {"decision": "request_changes"}, {"decision": "published"}, {"reason": " "}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with self.factory.begin() as session:
                    session.add(EditorialDecision(**(dict(draft_id=values["draft_id"], version_number=1,
                        content_hash=values["content_hash"], decision="approve", **ACTOR) | fields)))

    def test_command_event_keys_are_unique_and_hash_is_required(self):
        values = self.seed()
        with self.factory() as session:
            command_id = session.get(EditorialEvent, values["event_id"]).command_id
        for fields in ({"command_id": command_id, "request_hash": "a" * 64}, {"command_id": uuid4()},
                       {"request_hash": "a" * 64}, {"version_number": 99}, {"to_status": "published"}):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError):
                with self.factory.begin() as session:
                    session.add(EditorialEvent(**(dict(draft_id=values["draft_id"], event_type="test.event", **ACTOR) | fields)))

    def test_identity_and_concurrency_revision_cannot_be_bypassed_by_raw_updates(self):
        values = self.seed()
        for assignment in ("revision = revision + 2", "actor_subject = 'forged', revision = revision + 1",
                           "current_version_number = NULL, revision = revision + 1",
                           "status = 'published', revision = revision + 1"):
            with self.subTest(assignment=assignment), self.assertRaises(IntegrityError):
                with self.repository.engine.begin() as connection:
                    connection.execute(text("UPDATE editorial_drafts SET " + assignment))
        with self.repository.engine.begin() as connection:
            connection.execute(text("UPDATE editorial_drafts SET revision = revision + 1 WHERE id = :id"), {"id": values["draft_id"]})

    def test_two_independent_connections_cannot_silently_overwrite_a_draft(self):
        values = self.seed()
        other_engine = create_database_engine(self.runtime_config)
        try:
            with create_session_factory(self.repository.engine)() as one, create_session_factory(other_engine)() as two:
                first = one.get(EditorialDraft, values["draft_id"])
                second = two.get(EditorialDraft, values["draft_id"])
                first.status = "in_review"
                one.commit()
                second.status = "rejected"
                with self.assertRaises(StaleDataError):
                    two.commit()
                two.rollback()
            with self.factory() as session:
                self.assertEqual(session.get(EditorialDraft, values["draft_id"]).status, "in_review")
        finally:
            other_engine.dispose()

    def test_approved_state_requires_a_matching_version_specific_decision(self):
        values = self.seed(with_decision=False)
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.get(EditorialDraft, values["draft_id"]).status = "approved"
        with self.factory.begin() as session:
            session.add(EditorialDecision(draft_id=values["draft_id"], version_number=1,
                content_hash=values["content_hash"], decision="approve", **ACTOR))
            session.get(EditorialDraft, values["draft_id"]).status = "approved"
        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.add(EditorialDraftVersion(draft_id=values["draft_id"], version_number=2,
                    payload={"content": "Revised text"}, source_count=1, **ACTOR))
                session.flush()
                session.add(self.source_snapshot(values["draft_id"], 2, session.get(CollectedArticle, values["article_id"])))
                session.get(EditorialDraft, values["draft_id"]).current_version_number = 2
        with self.factory() as session:
            draft = session.get(EditorialDraft, values["draft_id"])
            self.assertEqual((draft.status, draft.current_version_number), ("approved", 1))

    def test_failed_unit_of_work_cannot_leave_partial_editorial_history(self):
        values = self.seed()
        before = {table: self.count(model) for table, model in (("versions", EditorialDraftVersion),
                  ("sources", EditorialVersionSource), ("events", EditorialEvent))}
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with self.factory.begin() as session:
                session.add(EditorialDraftVersion(draft_id=values["draft_id"], version_number=2,
                    payload={"content": "Must roll back"}, source_count=1, **ACTOR))
                session.flush()
                session.add(self.source_snapshot(values["draft_id"], 2, session.get(CollectedArticle, values["article_id"])))
                session.add(EditorialEvent(draft_id=values["draft_id"], version_number=2, event_type="test.rollback", **ACTOR))
                session.get(EditorialDraft, values["draft_id"]).current_version_number = 2
                session.flush()
                raise RuntimeError("abort")
        self.assertEqual(self.count(EditorialDraftVersion), before["versions"])
        self.assertEqual(self.count(EditorialVersionSource), before["sources"])
        self.assertEqual(self.count(EditorialEvent), before["events"])

    def test_hashes_are_generated_from_content_and_are_timezone_independent(self):
        values = self.seed()
        with self.engine.begin() as connection:
            expression = "public.hnh_editorial_snapshot_hash(source_id, article_id, source_name, source_url, external_id, original_url, canonical_url, published_at, input_text, captured_at)"
            for zone in ("UTC", "Europe/Belgrade"):
                connection.execute(text("SELECT set_config('TimeZone', :zone, true)"), {"zone": zone})
                actual = connection.execute(text("SELECT " + expression + " FROM editorial_version_sources")).scalar_one()
                self.assertEqual(actual, values["snapshot_hash"])
            for replacement in ("input_text || 'changed'",):
                changed = connection.execute(text("SELECT " + expression.replace("input_text,", replacement + ",") +
                                                  " FROM editorial_version_sources")).scalar_one()
                self.assertNotEqual(changed, values["snapshot_hash"])
            actual = connection.execute(text("SELECT public.hnh_identity_hash(payload::text) FROM editorial_draft_versions")).scalar_one()
            self.assertEqual(actual, values["content_hash"])

    def test_private_boundary_rejects_owner_unavailable_database_and_missing_grants(self):
        configs = (Settings(_env_file=None, news_storage_backend="postgres"),
                   self.runtime_config.model_copy(update={"postgres_host": "127.0.0.1", "postgres_port": 1}))
        for config in configs:
            application = create_app(config, editorial_identity_verifier=TestIdentityVerifier())
            try:
                with TestClient(application) as client:
                    response = client.get("/api/editorial/capabilities", headers={"Authorization": "Bearer fixture-reader"})
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertNotIn(config.postgres_password.get_secret_value(), response.text)
            finally:
                if "engine" in application.state.news_repository.__dict__:
                    application.state.news_repository.engine.dispose()
        with self.engine.begin() as connection:
            connection.execute(text(f'REVOKE SELECT ON TABLE editorial_events FROM "{self.role}"'))
        application = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/editorial/capabilities", headers={"Authorization": "Bearer fixture-reader"}).status_code, 503)
        finally:
            application.state.news_repository.engine.dispose()
            provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())

    def test_populated_collection_upgrade_downgrade_and_reupgrade_are_additive(self):
        with self.engine.begin() as connection:
            command.downgrade(alembic_config(connection), "20261030_02")
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)
        before = self.collection_snapshot()
        application = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/editorial/capabilities", headers={"Authorization": "Bearer fixture-reader"}).status_code, 503)
        finally:
            application.state.news_repository.engine.dispose()
        with self.engine.begin() as connection:
            command.upgrade(alembic_config(connection), "20261101_06")
            command.check(alembic_config(connection))
        provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
        self.assertEqual(self.collection_snapshot(), before)
        self.seed(collect=False)
        with self.engine.begin() as connection:
            command.downgrade(alembic_config(connection), "20261030_02")
        self.assertEqual(self.collection_snapshot(), before)
        with self.engine.begin() as connection:
            command.upgrade(alembic_config(connection), "20261101_06")
            command.check(alembic_config(connection))
        provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
        self.assertEqual(self.collection_snapshot(), before)
        self.assertEqual(self.count(EditorialDraft), 0)
