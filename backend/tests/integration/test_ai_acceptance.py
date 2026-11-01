"""Explicit acceptance, real PostgreSQL transactions and independent app instances."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import threading
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command as alembic_command
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.main import create_app
from app.models import (AIProcessingRun, AIProcessingEvent, EditorialDraft, EditorialDraftVersion,
    EditorialVersionSource, EditorialDecision, EditorialEvent)
from app.schemas.ai_processing import CreateSuggestion
from app.services.ai_processing import AIProcessing
from app.services.editorial_commands import EditorialCommands
from app.core.editorial_security import EditorialPrincipal, EditorialRole
from editorial_identity import TestIdentityVerifier
from integration.test_ai_processing import AIProcessingCase, BASE
from integration.test_persistent_collection import post, source
from tests.integration.test_postgresql import alembic_config

DRAFTS = "/api/editorial/drafts"


class AIAcceptanceTests(AIProcessingCase):
    def payload(self, **changes):
        return dict(headline="Urednički potvrđen naslov", body="Urednik je proverio tekst i potvrdio ovaj predlog.",
            excerpt="Potvrđen urednički predlog.", slug="potvrdjen-predlog", categories=["Kultura"], tags=["Region"],
            seo={"title": "Potvrđen naslov", "description": "Potvrđen opis."}, images=[],
            source_attribution=[{"article_id": self.article_id, "source_id": self.source_id}]) | changes

    def acceptance(self, revision=0, **changes):
        return dict(command_id=str(uuid4()), story_id=self.story_id, expected_revision=revision,
                    payload=self.payload(), confirm_acceptance=True) | changes

    def accept(self, suggestion, body=None, *, expected=200, client=None, role="editor"):
        response = (client or self.private).post(BASE + "/" + suggestion["id"] + "/accept",
            json=body or self.acceptance(), headers=self.headers(role))
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def draft(self, result):
        response = self.private.get(DRAFTS + "/" + result["draft_id"], headers=self.headers("reader"))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def manual(self):
        response = self.private.post(DRAFTS, headers=self.headers(), json=dict(command_id=str(uuid4()),
            expected_revision=0, story_id=self.story_id, target_locale="sr-Latn", payload=self.payload()))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def transition(self, state, action):
        response = self.private.post(DRAFTS + "/" + state["draft_id"] + "/" + action,
            headers=self.headers("reviewer" if action in {"approve", "reject", "request-changes"} else "editor"),
            json=dict(command_id=str(uuid4()), expected_revision=state["revision"], version_number=state["version_number"],
                content_hash=state["content_hash"], reason="Potrebna je urednička odluka.") if action != "submit" else
            dict(command_id=str(uuid4()), expected_revision=state["revision"], version_number=state["version_number"], content_hash=state["content_hash"]))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, state, **changes):
        response = self.private.post(DRAFTS + "/" + state["draft_id"] + "/revisions", headers=self.headers(),
            json=dict(command_id=str(uuid4()), expected_revision=state["revision"], payload=self.payload(**changes)))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def counts(self):
        return tuple(self.count(model) for model in (EditorialDraft, EditorialDraftVersion, EditorialVersionSource,
            EditorialDecision, EditorialEvent, AIProcessingEvent))

    def test_accept_creates_editing_workspace_and_paired_immutable_receipts(self):
        suggestion = self.create()
        body = self.acceptance()
        result = self.accept(suggestion, body)
        self.assertEqual((result["status"], result["revision"], result["version_number"]), ("editing", 1, 1))
        draft = self.draft(result)
        self.assertFalse(draft["effective_approval"])
        self.assertEqual(draft["current_version"]["origin"], "ai")
        self.assertEqual(draft["current_version"]["payload"], body["payload"])
        frozen = draft["current_version"]["sources"][0]
        for name in ("source_id", "article_id", "source_name", "source_url", "external_id", "original_url",
                     "canonical_url", "published_at", "input_text", "captured_at"):
            self.assertEqual(frozen[name], suggestion["input"]["source"][name], name)
        ai = self.read(suggestion["id"])
        self.assertEqual((ai["status"], ai["revision"], ai["input"], ai["output"]),
            ("accepted", 3, suggestion["input"], suggestion["output"]))
        self.assertEqual(ai["events"][-1]["result"], result)
        with self.factory() as session:
            event = session.scalar(select(EditorialEvent))
            run = session.get(AIProcessingRun, UUID(suggestion["id"]))
            provenance = event.details["ai_provenance"]
            self.assertEqual(event.event_type, "draft.accept_ai")
            self.assertEqual(event.details["result"], result)
            self.assertEqual((run.accepted_draft_id, run.accepted_version_number, run.accepted_content_hash),
                (UUID(result["draft_id"]), result["version_number"], result["content_hash"]))
            self.assertEqual(event.occurred_at, run.accepted_at)
            self.assertEqual((provenance["suggestion_id"], provenance["input_hash"], provenance["output_hash"]),
                (suggestion["id"], suggestion["input_hash"], suggestion["output_hash"]))
            self.assertEqual(provenance["provider"], suggestion["provenance"])
            self.assertEqual(provenance["prompt_version"], suggestion["input"]["prompt_version"])
            self.assertTrue(provenance["provider"]["is_mock"])
            self.assertEqual(event.actor_subject, "test-editor")
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 3))

    def test_accept_recollected_source_uses_original_frozen_input_and_metadata(self):
        suggestion = self.create()
        self.collect([source(posts=[post(title="Recollected changed headline", content="Changed upstream article text", language="en")])])
        result = self.accept(suggestion)
        evidence = self.draft(result)["current_version"]["sources"][0]
        self.assertEqual(evidence["input_text"], suggestion["input"]["source"]["input_text"])
        self.assertNotIn("Changed upstream", evidence["input_text"])
        self.assertEqual(evidence["captured_at"], suggestion["input"]["source"]["captured_at"])
        later = self.save(result, headline="Naknadna ručna izmena")
        later_evidence = self.draft(later)["current_version"]["sources"][0]
        self.assertEqual({k:v for k,v in later_evidence.items() if k != "id"}, {k:v for k,v in evidence.items() if k != "id"})

    def test_existing_approved_draft_gets_new_version_and_loses_effective_approval(self):
        original = self.manual()
        approved = self.transition(self.transition(original, "submit"), "approve")
        before = self.draft(approved)
        suggestion = self.create()
        result = self.accept(suggestion, self.acceptance(approved["revision"]))
        current = self.draft(result)
        self.assertEqual((result["status"], result["revision"], result["version_number"]), ("editing", approved["revision"] + 1, 2))
        self.assertFalse(current["effective_approval"])
        historical = self.private.get(f"{DRAFTS}/{result['draft_id']}/versions/1", headers=self.headers("reader")).json()
        self.assertEqual(historical, before["current_version"])
        self.assertEqual(self.count(EditorialDecision), 1)
        self.assertEqual(current["current_version"]["origin"], "ai")
        stale = self.private.post(f"{DRAFTS}/{result['draft_id']}/approve", headers=self.headers("reviewer"),
            json=dict(command_id=str(uuid4()), expected_revision=result["revision"], version_number=1, content_hash=original["content_hash"]))
        self.assertEqual(stale.status_code, 409)

    def test_requested_changes_can_accept_but_submitted_and_rejected_require_existing_transitions(self):
        original = self.manual()
        submitted = self.transition(original, "submit")
        suggestion = self.create()
        counts = self.counts()
        self.accept(suggestion, self.acceptance(submitted["revision"]), expected=409)
        self.assertEqual(self.counts(), counts)
        changes = self.transition(submitted, "request-changes")
        accepted = self.accept(suggestion, self.acceptance(changes["revision"]))
        rejected = self.transition(self.transition(accepted, "submit"), "reject")
        other = self.create()
        before = self.draft(rejected)
        self.accept(other, self.acceptance(rejected["revision"]), expected=409)
        self.assertEqual(self.draft(rejected), before)
        reopened = self.transition(rejected, "reopen")
        self.assertEqual(self.accept(other, self.acceptance(reopened["revision"]))["status"], "editing")

    def test_stale_revision_and_wrong_story_leave_both_sides_unchanged(self):
        original = self.manual()
        suggestion = self.create()
        before, counts = self.draft(original), self.counts()
        for body in (self.acceptance(), self.acceptance(original["revision"] + 1),
                     self.acceptance(original["revision"], story_id=str(uuid4()))):
            self.accept(suggestion, body, expected=409)
        self.assertEqual(self.draft(original), before)
        self.assertEqual(self.counts(), counts)
        self.assertEqual(self.read(suggestion["id"])["status"], "succeeded")

    def test_explicit_strict_confirmation_and_server_owned_metadata(self):
        suggestion = self.create()
        for value in (False, 0, 1, "true", None):
            self.accept(suggestion, self.acceptance(confirm_acceptance=value), expected=422)
        missing = self.acceptance()
        del missing["confirm_acceptance"]
        self.accept(suggestion, missing, expected=422)
        for changes in ({"origin": "manual"}, {"actor_subject": "forged"}, {"provider": "real-provider"}, {"ai_provenance": {}}):
            self.accept(suggestion, self.acceptance(**changes), expected=422)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 2))

    def test_attribution_cannot_change_or_add_another_portal_with_same_external_id(self):
        suggestion = self.create()
        self.collect([source("second", posts=[post(url="https://second.invalid/article")])])
        other = self.private.get(f"/api/editorial/stories/{self.story_id}/sources", headers=self.headers("reader")).json()
        other = next(row for row in other if row["article_id"] != self.article_id)
        wrong = {"article_id": other["article_id"], "source_id": other["source_id"]}
        self.assertEqual(other["external_id"], "1")
        for attribution in ([wrong], self.payload()["source_attribution"] + [wrong],
                            [{"article_id": self.article_id, "source_id": other["source_id"]}]):
            self.accept(suggestion, self.acceptance(payload=self.payload(source_attribution=attribution)), expected=422)
        self.assertEqual(self.count(EditorialDraftVersion), 0)

    def test_pending_failed_rejected_and_consumed_suggestions_cannot_be_accepted(self):
        principal = EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR}))
        processor = AIProcessing(self.private_app.state.news_repository, principal, self.provider)
        pending, _ = processor.reserve(CreateSuggestion(**self.creation()))
        self.accept({"id": str(pending.id)}, expected=409)
        self.provider.transform = lambda result, request: {"invalid": True}
        failed = self.create()
        self.accept(failed, expected=409)
        self.provider.transform = None
        rejected = self.create()
        self.private.post(BASE + "/" + rejected["id"] + "/reject", headers=self.headers(),
            json=dict(command_id=str(uuid4()), expected_revision=2, reason="Odbačen predlog."))
        self.accept(rejected, expected=409)
        accepted = self.create()
        self.accept(accepted)
        self.accept(accepted, self.acceptance(1), expected=409)
        self.accept({"id": str(uuid4())}, expected=404)

    def test_duplicate_receipt_remains_original_after_later_review_and_manual_save(self):
        suggestion = self.create()
        body = self.acceptance()
        original = self.accept(suggestion, body)
        approved = self.transition(self.transition(original, "submit"), "approve")
        self.assertEqual(self.accept(suggestion, body), original)
        self.assertTrue(self.draft(approved)["effective_approval"])
        saved = self.save(approved, headline="Nova ručna verzija")
        self.assertEqual(self.accept(suggestion, body), original)
        self.assertEqual(self.draft(saved)["current_version"]["origin"], "manual")
        self.assertEqual((self.count(EditorialDraftVersion), self.count(AIProcessingEvent)), (2, 3))

    def test_reused_command_with_changed_payload_identity_or_suggestion_conflicts(self):
        suggestion, other = self.create(), self.create()
        body = self.acceptance()
        self.accept(suggestion, body)
        for changed in (body | {"payload": self.payload(headline="Drugi naslov")}, body | {"expected_revision": 1},
                        body | {"story_id": str(uuid4())}):
            self.accept(suggestion, changed, expected=409)
        self.accept(suggestion, body, role="administrator", expected=409)
        self.accept(other, body, expected=409)
        self.assertEqual((self.count(EditorialDraftVersion), self.count(AIProcessingEvent)), (1, 5))

    def test_collisions_with_generation_and_manual_command_ids_are_rejected(self):
        generation = self.creation()
        suggestion = self.create(generation)
        self.accept(suggestion, self.acceptance(command_id=generation["command_id"]), expected=409)
        manual = self.manual()
        self.accept(suggestion, self.acceptance(manual["revision"], command_id=manual["command_id"]), expected=409)
        self.assertEqual(self.read(suggestion["id"])["status"], "succeeded")

    def parallel(self, actions):
        other_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        barrier = threading.Barrier(2)
        def invoke(client, action):
            barrier.wait(10)
            path, body = action
            return client.post(path, json=body, headers=self.headers())
        try:
            with TestClient(other_app) as other, ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(invoke, client, action) for client, action in zip((self.private, other), actions)]
                return [future.result(15) for future in futures]
        finally:
            other_app.state.news_repository.engine.dispose()

    def test_concurrent_identical_acceptance_returns_one_receipt(self):
        suggestion = self.create()
        action = (BASE + "/" + suggestion["id"] + "/accept", self.acceptance())
        responses = self.parallel([action, action])
        self.assertEqual([r.status_code for r in responses], [200, 200], [r.text for r in responses])
        self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 3))

    def test_concurrent_distinct_acceptance_commands_consume_once(self):
        suggestion = self.create()
        path = BASE + "/" + suggestion["id"] + "/accept"
        responses = self.parallel([(path, self.acceptance()), (path, self.acceptance())])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409], [r.text for r in responses])
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 3))

    def test_accept_reject_race_has_one_terminal_outcome(self):
        suggestion = self.create()
        path = BASE + "/" + suggestion["id"]
        responses = self.parallel([(path + "/accept", self.acceptance()), (path + "/reject",
            dict(command_id=str(uuid4()), expected_revision=2, reason="Urednik odbacuje predlog."))])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409], [r.text for r in responses])
        status = self.read(suggestion["id"])["status"]
        self.assertEqual(self.count(EditorialDraftVersion), int(status == "accepted"))
        self.assertEqual(self.count(AIProcessingEvent), 3)

    def test_two_suggestions_cannot_create_duplicate_story_workspaces(self):
        suggestions = [self.create(), self.create()]
        responses = self.parallel([(BASE + "/" + row["id"] + "/accept", self.acceptance()) for row in suggestions])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409], [r.text for r in responses])
        self.assertEqual((self.count(EditorialDraft), self.count(EditorialDraftVersion)), (1, 1))

    def test_acceptance_and_manual_save_enforce_same_revision(self):
        manual = self.manual()
        suggestion = self.create()
        responses = self.parallel([(BASE + "/" + suggestion["id"] + "/accept", self.acceptance(manual["revision"])),
            (DRAFTS + "/" + manual["draft_id"] + "/revisions", dict(command_id=str(uuid4()),
                expected_revision=manual["revision"], payload=self.payload(headline="Paralelna ručna izmena")))])
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409], [r.text for r in responses])
        self.assertEqual(self.count(EditorialDraftVersion), 2)

    def test_lost_response_and_restart_recover_without_provider_or_duplicate_version(self):
        suggestion = self.create()
        body = self.acceptance()
        app = self.private_app
        class LoseResponse:
            async def __call__(self, scope, receive, send):
                if scope["type"] == "http" and scope["path"].endswith("/accept"):
                    async def discard(message):
                        pass
                    await app(scope, receive, discard)
                    raise RuntimeError("injected lost response after commit")
                await app(scope, receive, send)
        with TestClient(LoseResponse(), raise_server_exceptions=False) as lossy:
            response = lossy.post(BASE + "/" + suggestion["id"] + "/accept", headers=self.headers(), json=body)
            self.assertEqual(response.status_code, 500)
        restarted = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(restarted) as client:
                result = self.accept(suggestion, body, client=client)
                self.assertEqual(result, self.read(suggestion["id"])["events"][-1]["result"])
        finally:
            restarted.state.news_repository.engine.dispose()
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1, 3))

    def test_failure_after_version_and_audit_rolls_back_both_sides(self):
        suggestion = self.create()
        original = AIProcessing.event
        def fail(processor, session, run, action, **kwargs):
            if action == "suggestion.accepted":
                raise RuntimeError("injected after editorial write")
            return original(processor, session, run, action, **kwargs)
        body = self.acceptance()
        with patch.object(AIProcessing, "event", fail), TestClient(self.private_app, raise_server_exceptions=False) as client:
            response = client.post(BASE + "/" + suggestion["id"] + "/accept", headers=self.headers(), json=body)
            self.assertEqual(response.status_code, 500)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 2))
        self.assertEqual(self.read(suggestion["id"])["status"], "succeeded")
        self.accept(suggestion, body)

    def test_failure_rolls_back_approved_head_and_preserves_old_decisions(self):
        approved = self.transition(self.transition(self.manual(), "submit"), "approve")
        before = self.draft(approved)
        suggestion = self.create()
        counts = self.counts()
        with patch.object(AIProcessing, "event", side_effect=RuntimeError("injected acceptance failure")), \
                TestClient(self.private_app, raise_server_exceptions=False) as client:
            response = client.post(BASE + "/" + suggestion["id"] + "/accept", headers=self.headers(),
                json=self.acceptance(approved["revision"]))
            self.assertEqual(response.status_code, 500)
        self.assertEqual(self.draft(approved), before)
        self.assertEqual(self.counts(), counts)

    def test_database_rejects_refreshed_evidence_even_if_shared_writer_is_faulty(self):
        suggestion = self.create()
        original = EditorialCommands.add_version
        def corrupt(commands, session, draft, payload, number, snapshots, **kwargs):
            snapshots = deepcopy(snapshots)
            snapshots[0]["input_text"] = "This is refreshed text, not the frozen input."
            return original(commands, session, draft, payload, number, snapshots, **kwargs)
        with patch.object(EditorialCommands, "add_version", corrupt):
            self.accept(suggestion, expected=503)
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 2))
        self.assertEqual(self.read(suggestion["id"])["status"], "succeeded")

    def test_permissions_and_accepting_identity_come_from_server(self):
        suggestion = self.create()
        for role in ("reader", "reviewer", "publisher", "no-roles"):
            self.accept(suggestion, role=role, expected=403)
        self.assertEqual(self.private.post(BASE + "/" + suggestion["id"] + "/accept", json=self.acceptance()).status_code, 401)
        result = self.accept(suggestion, role="administrator")
        self.assertEqual(self.draft(result)["current_version"]["actor_subject"], "test-administrator")
        self.assertEqual(self.read(suggestion["id"])["events"][-1]["actor_subject"], "test-administrator")

    def test_complete_editor_confirmed_payload_is_saved_without_using_mock_body(self):
        suggestion = self.create()
        payload = self.payload(categories=["Kultura\nRegion", "Muzika, film"], tags=["Događaji\tRegion"],
            images=[{"url": "https://source.invalid/editor-image.jpg", "alt": "Opis slike", "credit": "Portal",
                     "source_article_id": self.article_id}])
        result = self.accept(suggestion, self.acceptance(payload=payload))
        self.assertEqual(self.draft(result)["current_version"]["payload"], payload)
        self.assertNotEqual(payload["body"], suggestion["output"]["body"])

    def test_accepted_history_is_immutable_and_downgrade_fails_safely(self):
        suggestion = self.create()
        result = self.accept(suggestion)
        before = self.read(suggestion["id"])
        with self.engine.connect() as conn:
            revision_before = conn.scalar(text("SELECT version_num FROM public.alembic_version"))
        for statement in ("UPDATE public.ai_processing_runs SET accepted_version_number=99, revision=revision+1",
                          "UPDATE public.ai_processing_events SET result='{}'::jsonb",
                          "DELETE FROM public.ai_processing_events"):
            with self.assertRaises(SQLAlchemyError), self.private_app.state.news_repository.engine.begin() as conn:
                conn.execute(text(statement))
        with self.assertRaises(SQLAlchemyError), self.engine.begin() as conn:
            alembic_command.downgrade(alembic_config(conn), "20261101_04")
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(text("SELECT version_num FROM public.alembic_version")), revision_before)
        self.assertEqual(self.read(suggestion["id"]), before)
        self.assertEqual(self.draft(result)["current_version"]["origin"], "ai")

    def test_populated_04_upgrade_preserves_existing_ai_and_editorial_data(self):
        original = self.manual()
        self.create()
        with self.engine.begin() as connection:
            config = alembic_config(connection)
            alembic_command.downgrade(config, "20261101_04")
            before = connection.execute(text("SELECT input_payload::text,input_hash,output::text,output_hash FROM public.ai_processing_runs")).one()
            old_events = connection.execute(text("SELECT to_jsonb(e) FROM public.ai_processing_events e ORDER BY revision")).scalars().all()
            alembic_command.upgrade(config, "head")
            after = connection.execute(text("SELECT input_payload::text,input_hash,output::text,output_hash FROM public.ai_processing_runs")).one()
            new_events = connection.execute(text("SELECT to_jsonb(e)-'result' FROM public.ai_processing_events e ORDER BY revision")).scalars().all()
            self.assertEqual(before, after)
            self.assertEqual(old_events, new_events)
            alembic_command.check(config)
        self.assertEqual(self.draft(original)["current_version"]["origin"], "manual")
