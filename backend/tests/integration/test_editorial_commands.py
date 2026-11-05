"""Real command/API transactions on disposable PostgreSQL, using the runtime role."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from app.main import create_app
from app.models import (CollectedArticle, EditorialDraft, EditorialDraftVersion, EditorialDecision,
    EditorialEvent, EditorialVersionSource)
from app.database.runtime_security import EDITORIAL_HISTORY_TABLES
from app.services.editorial_commands import EditorialCommands, EditorialCommandError
from app.schemas.editorial_commands import RevisionCommand
from editorial_identity import TestIdentityVerifier
from integration.test_persistent_collection import PersistentCollectionCase, post, source

BASE = "/api/editorial/drafts"


class EditorialCommandTests(PersistentCollectionCase):
    def setUp(self):
        super().setUp()
        result = self.collect([source(posts=[post()])])
        self.assertEqual(result.status_code, 200, result.text)
        self.story_id = result.json()["stories"][0]["id"]
        with self.factory() as session:
            article = session.scalar(select(CollectedArticle))
            self.article_id, self.source_id = str(article.id), str(article.source_id)
        self.private_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        self.private = TestClient(self.private_app)

    def tearDown(self):
        self.private.close()
        if "engine" in self.private_app.state.news_repository.__dict__:
            self.private_app.state.news_repository.engine.dispose()
        with self.engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE " + ", ".join(("ai_processing_events", "ai_processing_runs", "editorial_drafts", *EDITORIAL_HISTORY_TABLES))))
        super().tearDown()

    def headers(self, role="editor"):
        return {"Authorization": "Bearer fixture-" + role}

    def payload(self, **updates):
        return dict(headline="Regionalni festival počinje večeras", body="Proverene činjenice iz izvora.\n\nUrednički tekst na srpskom.",
            excerpt="Festival počinje večeras.", slug="regionalni-festival", categories=["Zabava"], tags=["Festival"],
            seo={"title": "Regionalni festival", "description": "Najvažnije informacije o festivalu."}, images=[],
            source_attribution=[{"article_id": self.article_id, "source_id": self.source_id}], **updates)

    def creation(self, **updates):
        values = dict(command_id=str(uuid4()), expected_revision=0, story_id=self.story_id,
            target_locale="sr-Latn", payload=self.payload())
        return values | updates

    def create(self, **updates):
        response = self.private.post(BASE, json=self.creation(**updates), headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def command(self, result, action, role=None, status=200, **updates):
        body = dict(command_id=str(uuid4()), expected_revision=result["revision"])
        if action == "revisions":
            body["payload"] = self.payload() | {"headline": "Novi urednički naslov " + str(result["revision"])}
        else:
            body.update(version_number=result["version_number"], content_hash=result["content_hash"])
            if action in {"request-changes", "reject", "reopen"}:
                body["reason"] = "Potrebna urednička provera činjenica."
        body.update(updates)
        role = role or ("reviewer" if action in {"approve", "request-changes", "reject"} else "editor")
        response = self.private.post(f"{BASE}/{result['draft_id']}/{action}", json=body, headers=self.headers(role))
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def read(self, result):
        response = self.private.get(f"{BASE}/{result['draft_id']}", headers=self.headers("reader"))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_complete_lifecycle_and_frozen_append_only_history(self):
        result = self.create()
        self.assertEqual((result["revision"], result["version_number"], result["status"]), (1, 1, "editing"))
        for action, status in [("revisions", "editing"), ("submit", "in_review"), ("request-changes", "changes_requested"),
            ("revisions", "editing"), ("submit", "in_review"), ("reject", "rejected"), ("reopen", "editing"),
            ("submit", "in_review"), ("approve", "approved"), ("revisions", "editing")]:
            previous = result
            result = self.command(result, action)
            self.assertEqual(result["revision"], previous["revision"] + 1)
            self.assertEqual(result["status"], status)
            self.assertEqual(self.read(result)["effective_approval"], status == "approved")
        self.assertEqual((self.count(EditorialDraftVersion), self.count(EditorialVersionSource), self.count(EditorialDecision), self.count(EditorialEvent)), (4, 4, 3, 11))
        events = self.private.get(f"{BASE}/{result['draft_id']}/events", headers=self.headers("reader")).json()
        self.assertEqual([event["details"]["result"]["revision"] for event in events], list(range(1,12)))
        self.assertEqual([event["actor_subject"] for event in events if event["event_type"] == "draft.approve"], ["test-reviewer"])
        self.assertEqual(events[7]["details"]["reason"], "Potrebna urednička provera činjenica.")

    def test_source_snapshot_survives_recollection_and_manual_edit(self):
        result = self.create()
        original = self.read(result)["current_version"]
        self.collect([source(posts=[post(title="Changed source headline", content="Changed upstream text")])])
        saved = self.command(result, "revisions")
        current = self.read(saved)["current_version"]
        self.assertEqual(current["sources"][0]["input_text"], original["sources"][0]["input_text"])
        self.assertEqual(current["sources"][0]["captured_at"], original["sources"][0]["captured_at"])
        self.assertEqual(current["sources"][0]["snapshot_hash"], original["sources"][0]["snapshot_hash"])
        history = self.private.get(f"{BASE}/{result['draft_id']}/versions", headers=self.headers("reader")).json()
        detail = self.private.get(f"{BASE}/{result['draft_id']}/versions/1", headers=self.headers("reader")).json()
        self.assertEqual(detail, original)
        for name in ("id", "version_number", "content_hash", "actor_issuer", "actor_subject", "created_at"):
            self.assertEqual(history[0][name], original[name])
        self.assertNotIn("payload",history[0])
        self.assertNotIn("sources",history[0])
        self.assertNotEqual(history[1]["content_hash"], original["content_hash"])

    def test_same_external_id_from_another_story_is_not_an_attribution(self):
        other = self.collect([source("unrelated", posts=[post(title="Completely unrelated parliamentary budget decision", url="https://unrelated.invalid/post")])])
        self.assertEqual(other.status_code,200)
        with self.factory() as session:
            unrelated = session.scalar(select(CollectedArticle).where(CollectedArticle.source_id != UUID(self.source_id)))
            bad = self.payload() | {"source_attribution": [{"article_id": str(unrelated.id), "source_id": str(unrelated.source_id)}]}
        response = self.private.post(BASE,json=self.creation(payload=bad),headers=self.headers())
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.count(EditorialDraft),0)
        result=self.create()
        self.command(result,"revisions",payload=bad,status=422)
        forged=self.payload() | {"source_attribution":[{"article_id": self.article_id, "source_id": str(uuid4())}]}
        self.command(result,"revisions",payload=forged,status=422)
        self.assertEqual(self.count(EditorialDraftVersion),1)

    def test_added_story_source_gets_complete_new_snapshot(self):
        result=self.create()
        self.collect([source("second",posts=[post(url="https://second.invalid/item")])])
        with self.factory() as session:
            other=session.scalar(select(CollectedArticle).where(CollectedArticle.source_id != UUID(self.source_id)))
            attribution={"article_id":str(other.id),"source_id":str(other.source_id)}
        payload=self.payload()
        payload["source_attribution"].append(attribution)
        saved=self.command(result,"revisions",payload=payload)
        sources=self.read(saved)["current_version"]["sources"]
        self.assertEqual(len(sources),2)
        self.assertTrue(all(row["source_name"] and row["source_url"] and row["original_url"] and row["input_text"] and row["captured_at"] and row["snapshot_hash"] for row in sources))

    def test_invalid_transitions_and_unchanged_payload_do_not_write_history(self):
        result=self.create()
        for action in ["approve","request-changes","reject","reopen"]:
            self.command(result,action,status=409)
        self.command(result,"revisions",payload=self.payload(),status=422)
        submitted=self.command(result,"submit")
        for action in ["submit","reopen","revisions"]:
            self.command(submitted,action,status=409)
        rejected=self.command(submitted,"reject")
        self.command(rejected,"revisions",status=409)
        self.command(rejected,"submit",status=409)
        reopened=self.command(rejected,"reopen")
        self.assertEqual(reopened["status"],"editing")
        self.assertEqual(self.count(EditorialDraftVersion),1)

    def test_requested_changes_can_reopen_without_mutating_content(self):
        result=self.command(self.command(self.create(),"submit"),"request-changes")
        reopened=self.command(result,"reopen")
        self.assertEqual((reopened["status"], reopened["version_number"]),("editing",1))

    def test_old_approval_is_ineffective_after_new_revision_and_later_rejection(self):
        approved=self.command(self.command(self.create(),"submit"),"approve")
        self.assertTrue(self.read(approved)["effective_approval"])
        saved=self.command(approved,"revisions")
        self.assertFalse(self.read(saved)["effective_approval"])
        rejected=self.command(self.command(saved,"submit"),"reject")
        reopened=self.command(rejected,"reopen")
        submitted=self.command(reopened,"submit")
        self.assertFalse(self.read(submitted)["effective_approval"])
        current=self.command(submitted,"approve")
        self.assertTrue(self.read(current)["effective_approval"])
        self.assertEqual(self.count(EditorialDecision),3)

    def test_unpaired_later_negative_decision_invalidates_approval(self):
        approved=self.command(self.command(self.create(),"submit"),"approve")
        with self.factory.begin() as session:
            session.add(EditorialDecision(draft_id=UUID(approved["draft_id"]),version_number=approved["version_number"],
                content_hash=approved["content_hash"],decision="reject",reason="Owner legacy import",actor_issuer="legacy",actor_subject="legacy"))
        self.assertFalse(self.read(approved)["effective_approval"])

    def test_stale_revision_and_wrong_version_hash_are_conflicts(self):
        first=self.create()
        second=self.command(first,"revisions")
        for action in ["revisions","submit","approve","request-changes","reject","reopen"]:
            self.command(first,action,status=409)
        self.command(second,"submit",content_hash="0"*64,status=409)
        self.command(second,"submit",version_number=1,status=409)
        self.assertEqual(self.count(EditorialEvent),2)

    def test_core_sql_revision_predicate_checks_affected_rows(self):
        result=self.create()
        service=EditorialCommands(self.private_app.state.news_repository,
            TestIdentityVerifier().identities["fixture-editor"])
        command=RevisionCommand(command_id=uuid4(),expected_revision=result["revision"]+1)
        with self.assertRaises(EditorialCommandError) as caught:
            with service.transaction() as session:
                draft=session.get(EditorialDraft,UUID(result["draft_id"]))
                service.cas(session,draft,command,"editing",1)
        self.assertEqual(caught.exception.status,409)
        self.assertEqual(self.read(result)["revision"],result["revision"])

    def test_real_cross_workspace_hash_cannot_authorize_a_decision(self):
        first=self.create()
        collected=self.collect([source("other",posts=[post(title="Parliamentary budget legislation passed",url="https://other.invalid/article")])])
        other_story=next(row["id"] for row in collected.json()["stories"] if row["id"] != self.story_id)
        with self.factory() as session:
            article=session.scalar(select(CollectedArticle).where(CollectedArticle.source_id != UUID(self.source_id)))
            other_payload=self.payload()|{"source_attribution":[{"article_id":str(article.id),"source_id":str(article.source_id)}]}
        second=self.create(story_id=other_story,payload=other_payload)
        submitted=self.command(first,"submit")
        self.command(submitted,"approve",content_hash=second["content_hash"],status=409)
        self.assertEqual(self.count(EditorialDecision),0)

    def test_private_source_lookup_exposes_stable_ids_without_changing_public_projection(self):
        path=f"/api/editorial/stories/{self.story_id}/sources"
        self.assertEqual(self.private.get(path).status_code,401)
        response=self.private.get(path,headers=self.headers("reader"))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual((response.json()[0]["article_id"],response.json()[0]["source_id"]),(self.article_id,self.source_id))
        self.assertEqual(self.private.get(path+"?offset=1",headers=self.headers("reader")).json(),[])

    def test_large_source_input_is_rejected_without_truncation_or_partial_workspace(self):
        self.collect([source(posts=[post(content="x"*(4*1024*1024))])])
        response=self.private.post(BASE,json=self.creation(),headers=self.headers())
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual((self.count(EditorialDraft),self.count(EditorialVersionSource)),(0,0))

    def test_cross_draft_version_and_client_actor_fields_are_rejected(self):
        result=self.create()
        self.command(result,"submit",version_number=999,status=409)
        self.command(result,"submit",content_hash="f"*64,status=409)
        self.command(result,"revisions",actor_subject="admin",status=422)
        self.command(result,"revisions",roles=["administrator"],status=422)
        response=self.private.post(f"{BASE}/{uuid4()}/submit",headers=self.headers(),json=dict(command_id=str(uuid4()),expected_revision=1,version_number=1,content_hash=result["content_hash"]))
        self.assertEqual(response.status_code,404)

    def test_command_retries_return_original_receipts_after_later_changes(self):
        creation=self.creation()
        first=self.private.post(BASE,json=creation,headers=self.headers()).json()
        self.assertEqual(self.private.post(BASE,json=creation,headers=self.headers()).json(),first)
        submitted=self.command(first,"submit")
        decision_id=str(uuid4())
        approved=self.command(submitted,"approve",command_id=decision_id)
        self.command(approved,"revisions")
        replayed=self.command(submitted,"approve",command_id=decision_id)
        self.assertEqual(replayed,approved)
        self.assertFalse(self.read(approved)["effective_approval"])
        self.assertEqual(self.count(EditorialDecision),1)

    def test_command_ids_are_bound_to_action_payload_and_verified_identity(self):
        result=self.create()
        command_id=str(uuid4())
        saved=self.command(result,"revisions",command_id=command_id)
        self.command(result,"revisions",command_id=command_id,payload=self.payload()|{"headline":"Different request"},status=409)
        self.command(saved,"submit",command_id=command_id,status=409)
        self.command(result,"revisions",command_id=command_id,role="administrator",status=409)
        self.assertEqual(self.count(EditorialEvent),2)

    def concurrent(self, requests):
        barrier=threading.Barrier(len(requests))
        def run(request):
            app=create_app(self.runtime_config,editorial_identity_verifier=TestIdentityVerifier())
            try:
                with TestClient(app) as client:
                    barrier.wait(5)
                    return client.post(request[0],json=request[1],headers=self.headers(request[2]))
            finally:
                if "engine" in app.state.news_repository.__dict__:
                    app.state.news_repository.engine.dispose()
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run,requests))

    def test_concurrent_creation_from_independent_applications_has_one_workspace(self):
        responses=self.concurrent([(BASE,self.creation(),"editor"),(BASE,self.creation(),"editor")])
        self.assertEqual(sorted(response.status_code for response in responses),[201,409])
        self.assertEqual((self.count(EditorialDraft),self.count(EditorialDraftVersion),self.count(EditorialEvent)),(1,1,1))

    def test_concurrent_duplicate_create_command_replays_without_duplicates(self):
        command=self.creation()
        responses=self.concurrent([(BASE,command,"editor"),(BASE,command,"editor")])
        self.assertEqual([response.status_code for response in responses],[201,201])
        self.assertEqual(responses[0].json(),responses[1].json())
        self.assertEqual(self.count(EditorialEvent),1)

    def test_concurrent_saves_enforce_expected_revision(self):
        result=self.create()
        requests=[(f"{BASE}/{result['draft_id']}/revisions",dict(command_id=str(uuid4()),expected_revision=result["revision"],
            payload=self.payload()|{"headline":headline}),"editor") for headline in ["Prvi novi naslov","Drugi novi naslov"]]
        responses=self.concurrent(requests)
        self.assertEqual(sorted(response.status_code for response in responses),[200,409])
        self.assertEqual((self.count(EditorialDraftVersion),self.count(EditorialEvent)),(2,2))

    def test_concurrent_approval_and_rejection_cannot_both_commit(self):
        result=self.command(self.create(),"submit")
        body=dict(expected_revision=result["revision"],version_number=result["version_number"],content_hash=result["content_hash"])
        requests=[(f"{BASE}/{result['draft_id']}/{action}",body|{"command_id":str(uuid4()),"reason":"Provera odluke"},"reviewer") for action in ["approve","reject"]]
        responses=self.concurrent(requests)
        self.assertEqual(sorted(response.status_code for response in responses),[200,409])
        self.assertEqual(self.count(EditorialDecision),1)
        current=self.read(result)
        self.assertEqual(current["effective_approval"],current["status"]=="approved")

    def test_concurrent_approval_and_save_cannot_overwrite_decision(self):
        result=self.command(self.create(),"submit")
        body=dict(command_id=str(uuid4()),expected_revision=result["revision"],version_number=result["version_number"],content_hash=result["content_hash"])
        responses=self.concurrent([(f"{BASE}/{result['draft_id']}/approve",body,"reviewer"),
            (f"{BASE}/{result['draft_id']}/revisions",dict(command_id=str(uuid4()),expected_revision=result["revision"],payload=self.payload()|{"headline":"Concurrent edit"}),"editor")])
        self.assertEqual([response.status_code for response in responses],[200,409])
        self.assertEqual(self.read(result)["status"],"approved")

    def test_duplicate_concurrent_decision_retries_share_one_result(self):
        result=self.command(self.create(),"submit")
        body=dict(command_id=str(uuid4()),expected_revision=result["revision"],version_number=result["version_number"],content_hash=result["content_hash"])
        request=(f"{BASE}/{result['draft_id']}/approve",body,"reviewer")
        responses=self.concurrent([request,request])
        self.assertEqual([response.status_code for response in responses],[200,200])
        self.assertEqual(responses[0].json(),responses[1].json())
        self.assertEqual(self.count(EditorialDecision),1)

    def test_event_failure_rolls_back_revision_snapshots_decision_and_state(self):
        created=self.create()
        original=EditorialCommands.record
        def fail(service,*args,**kwargs):
            original(service,*args,**kwargs)
            raise RuntimeError("Injected failure after event INSERT")
        with patch.object(EditorialCommands,"record",fail):
            with self.assertRaisesRegex(RuntimeError,"Injected failure"):
                self.command(created,"revisions")
        self.assertEqual(self.read(created)["revision"],created["revision"])
        self.assertEqual((self.count(EditorialDraftVersion),self.count(EditorialVersionSource),self.count(EditorialEvent)),(1,1,1))
        submitted=self.command(created,"submit")
        with patch.object(EditorialCommands,"record",fail):
            with self.assertRaisesRegex(RuntimeError,"Injected failure"):
                self.command(submitted,"approve")
        self.assertEqual(self.read(submitted)["status"],"in_review")
        self.assertEqual(self.count(EditorialDecision),0)
        self.command(submitted,"approve")

    def test_failed_creation_rolls_back_workspace_and_can_retry_same_command(self):
        command=self.creation()
        with patch.object(EditorialCommands,"record",side_effect=RuntimeError("Injected creation failure")):
            with self.assertRaises(RuntimeError):
                self.private.post(BASE,json=command,headers=self.headers())
        self.assertEqual((self.count(EditorialDraft),self.count(EditorialDraftVersion),self.count(EditorialVersionSource)),(0,0,0))
        self.assertEqual(self.private.post(BASE,json=command,headers=self.headers()).status_code,201)

    def test_restart_retains_private_content_and_history_public_routes_exclude_it(self):
        result=self.command(self.create(),"revisions",payload=self.payload()|{"body":"PRIVATE SAVED EDITORIAL BODY"})
        before=self.read(result)
        other=create_app(self.runtime_config,editorial_identity_verifier=TestIdentityVerifier())
        with TestClient(other) as client:
            response=client.get(f"{BASE}/{result['draft_id']}",headers=self.headers("reader"))
            self.assertEqual(response.json(),before)
            self.assertEqual(len(client.get(f"{BASE}/{result['draft_id']}/events",headers=self.headers("reader")).json()),2)
        for path in ["/api/stories","/api/editorial-queue",f"/api/editorial-stories/{self.story_id}"]:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn("PRIVATE SAVED EDITORIAL BODY",response.text)

    def test_read_roles_pagination_and_workspace_lookup(self):
        result=self.create()
        self.assertEqual(self.private.get(BASE,params={"story_id":self.story_id},headers=self.headers("reader")).json(),self.read(result))
        for suffix in ["","/versions","/versions/1","/events"]:
            url=f"{BASE}/{result['draft_id']}{suffix}"
            self.assertEqual(self.private.get(url).status_code,401)
            for role in ["reader","editor","reviewer","publisher","administrator"]:
                response=self.private.get(url,headers=self.headers(role))
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers["cache-control"],"no-store")
            self.assertEqual(self.private.get(url,headers=self.headers("no-roles")).status_code,403)
        self.assertEqual(self.private.get(f"{BASE}/{result['draft_id']}/events?limit=101",headers=self.headers("reader")).status_code,422)
        self.assertEqual(self.private.get(f"{BASE}/{result['draft_id']}/events?offset=1",headers=self.headers("reader")).json(),[])

    def test_write_authorization_matrix_and_verified_actor_only(self):
        result=self.create()
        for role in ["reader","reviewer","publisher"]:
            self.assertEqual(self.private.post(BASE,json=self.creation(),headers=self.headers(role)).status_code,403)
            for action in ["revisions","submit","reopen"]:
                self.command(result,action,role=role,status=403)
        for role in ["reader","editor","publisher"]:
            for action in ["approve","request-changes","reject"]:
                self.command(result,action,role=role,status=403)
        submitted=self.command(result,"submit",role="administrator")
        self.command(submitted,"approve",role="administrator")

    def test_negative_decisions_and_reopening_require_nonblank_reasons(self):
        result=self.create()
        for action in ["reject","request-changes","reopen"]:
            self.command(result,action,reason=" ",status=422)

    def test_committed_command_history_cannot_be_mutated_by_runtime(self):
        self.command(self.command(self.create(),"submit"),"approve")
        for table in EDITORIAL_HISTORY_TABLES:
            for sql in [f"UPDATE {table} SET id=id",f"DELETE FROM {table}",f"TRUNCATE {table}"]:
                from sqlalchemy.exc import SQLAlchemyError
                with self.subTest(sql=sql),self.assertRaises(SQLAlchemyError) as caught:
                    with self.private_app.state.news_repository.engine.begin() as conn:
                        conn.execute(text(sql))
                self.assertEqual(caught.exception.orig.sqlstate,"42501")

    def editorial_snapshot(self):
        with self.engine.connect() as connection:
            return {table: connection.execute(text(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id), '[]'::jsonb) FROM {table} t"
            )).scalar_one() for table in ("editorial_drafts", *EDITORIAL_HISTORY_TABLES)}

    def measured_get(self, path):
        statements=[]
        def record(connection,cursor,statement,parameters,context,executemany):
            statements.append(statement)
        engine=self.private_app.state.news_repository.engine
        event.listen(engine,"before_cursor_execute",record)
        try:
            response=self.private.get(path,headers=self.headers("reader"))
        finally:
            event.remove(engine,"before_cursor_execute",record)
        return response,statements

    def test_malformed_inputs_return_safe_4xx_without_any_persisted_changes(self):
        approved=self.command(self.command(self.create(),"submit"),"approve")
        before=self.editorial_snapshot()
        malformed=[]
        for value in (float("nan"),float("inf"),float("-inf")):
            command=self.creation()
            command["payload"]["headline"]=value
            malformed.append((json.dumps(command).encode(),"application/json",400))
        for value in ("bad \ud800", "bad \udfff"):
            command=self.creation()
            command["payload"]["body"]=value
            malformed.append((json.dumps(command).encode(),"application/json",400))
        malformed += [(b'\xff',"application/octet-stream",415),(b'\xff',"application/json",400),
            (b'{"value":1e400}',"application/json",400),(b'{',"application/json",400),
            (b'[]',"application/json",422), (b'{"secret-field":"NEVER_REFLECT_THIS"}',"application/json",422)]
        for url in (BASE,f"{BASE}/{approved['draft_id']}/revisions"):
            for content,content_type,status in malformed:
                with self.subTest(path=url,content=repr(content[:40])):
                    response=self.private.post(url,content=content,headers=self.headers()|{"Content-Type":content_type})
                    self.assertEqual(response.status_code,status,response.text)
                    self.assertIsInstance(response.json()["detail"],str)
                    self.assertEqual(response.headers["cache-control"],"no-store")
                    self.assertNotIn("NEVER_REFLECT_THIS",response.text)
                    self.assertNotIn("secret-field",response.text)
                    self.assertNotIn("Unicode",response.text)
                    self.assertEqual(self.editorial_snapshot(),before)
        self.assertTrue(self.read(approved)["effective_approval"])

    def test_valid_json_unicode_media_types_and_retries_keep_existing_behavior(self):
        command=self.creation(payload=self.payload()|{"body":"Važeći srpski tekst čćšžđ. Fotografija 😀."})
        utf8=json.dumps(command,ensure_ascii=False).encode()
        ascii_body=json.dumps(command,ensure_ascii=True).encode()
        formats=[(utf8,"application/json"),(ascii_body,"application/json; charset=utf-8"),
            (utf8,'application/json; charset = "UTF-8"'),(utf8,"application/vnd.hype+json"),
            (b'\xef\xbb\xbf'+utf8,"application/json"),(utf8,None)]
        original=None
        for content,content_type in formats:
            headers=self.headers()
            if content_type:headers["Content-Type"]=content_type
            response=self.private.post(BASE,content=content,headers=headers)
            self.assertEqual(response.status_code,201,(content_type,response.text))
            if original is None:original=response.json()
            self.assertEqual(response.json(),original)
        self.assertEqual((self.count(EditorialDraftVersion),self.count(EditorialEvent)),(1,1))
        self.assertEqual(self.read(original)["current_version"]["payload"],command["payload"])

    def test_large_history_is_metadata_only_and_has_constant_query_count(self):
        self.collect([source(posts=[post(content="x"*(2*1024*1024))])])
        result=self.create()
        original=self.read(result)["current_version"]
        for number in range(2,51):
            result=self.command(result,"revisions",payload=self.payload()|{"body":f"PRIVATE HISTORY VERSION {number}"})
        path=f"{BASE}/{result['draft_id']}/versions"
        measurements=[]
        for limit in (1,5,20,50):
            response,statements=self.measured_get(path+f"?limit={limit}")
            self.assertEqual(response.status_code,200,response.text)
            summaries=response.json()
            self.assertEqual(len(summaries),limit)
            self.assertEqual([row["version_number"] for row in summaries],list(range(1,limit+1)))
            self.assertTrue(all(set(row)=={"id","version_number","payload_schema_version","content_hash","source_count","origin","actor_issuer","actor_subject","created_at"} for row in summaries))
            self.assertTrue(all(row["source_count"]==1 for row in summaries))
            self.assertLess(len(response.content),256*1024)
            self.assertFalse(any(re.search(r"editorial_draft_versions\.payload(?:\s|,|$)",sql)
                or "editorial_version_sources.input_text" in sql for sql in statements))
            measurements.append((limit,len(response.content),len(statements)))
        self.assertEqual(len({count for _,_,count in measurements}),1,measurements)
        self.assertLessEqual(measurements[0][2],12,measurements)
        detail,statements=self.measured_get(path+"/1")
        self.assertEqual(detail.status_code,200,detail.text[:100])
        self.assertEqual(detail.json(),original)
        self.assertLessEqual(len(statements),13)
        self.assertGreater(len(detail.content),2*1024*1024)
        self.assertLess(len(detail.content),32*1024*1024)
        print("HARDENING history (limit, bytes, SQL statements):",measurements,flush=True)
        print("HARDENING single 2 MiB evidence version (bytes, SQL statements):",len(detail.content),len(statements),flush=True)
        pages=[]
        for offset in (0,20,40):
            response=self.private.get(path+f"?offset={offset}",headers=self.headers("reader"))
            self.assertEqual(response.status_code,200)
            pages.extend(row["version_number"] for row in response.json())
        self.assertEqual(pages,list(range(1,51)))
        self.assertEqual(self.private.get(path+"?limit=51",headers=self.headers("reader")).status_code,422)
        self.assertEqual(self.private.get(path+"/51",headers=self.headers("reader")).status_code,404)
        self.assertEqual(self.private.get(path+"/0",headers=self.headers("reader")).status_code,422)
        app=create_app(self.runtime_config,editorial_identity_verifier=TestIdentityVerifier())
        with TestClient(app) as restarted:
            response=restarted.get(path+"/1",headers=self.headers("reader"))
            self.assertEqual(response.json(),original)
        for public_path in ("/api/stories","/api/editorial-queue",f"/api/editorial-stories/{self.story_id}"):
            self.assertNotIn("PRIVATE HISTORY VERSION",self.client.get(public_path).text)

    def test_history_and_detail_budgets_reject_safely_without_history_mutation(self):
        self.collect([source(posts=[post(content="x"*(2*1024*1024))])])
        result=self.create();path=f"{BASE}/{result['draft_id']}/versions"
        before=self.editorial_snapshot()
        with patch("app.services.editorial_commands.MAX_VERSION_RESPONSE_BYTES",1024):
            response,statements=self.measured_get(path+"/1")
        self.assertEqual(response.status_code,422,response.text)
        self.assertFalse(any("editorial_version_sources.input_text" in sql for sql in statements))
        self.assertEqual(self.editorial_snapshot(),before)
        with patch("app.services.editorial_commands.MAX_HISTORY_RESPONSE_BYTES",64):
            response=self.private.get(path,headers=self.headers("reader"))
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.editorial_snapshot(),before)
        self.assertEqual(self.private.get(path+"/1",headers=self.headers("reader")).status_code,200)

    def test_version_detail_is_draft_scoped_and_reader_protected(self):
        result=self.create();path=f"{BASE}/{result['draft_id']}/versions"
        before=self.editorial_snapshot()
        for suffix in ("","/1"):
            self.assertEqual(self.private.get(path+suffix).status_code,401)
            self.assertEqual(self.private.get(path+suffix,headers=self.headers("no-roles")).status_code,403)
            for role in ("reader","editor","reviewer","publisher","administrator"):
                response=self.private.get(path+suffix,headers=self.headers(role))
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual(self.private.get(f"{BASE}/{uuid4()}/versions/1",headers=self.headers("reader")).status_code,404)
        self.assertEqual(self.editorial_snapshot(),before)
