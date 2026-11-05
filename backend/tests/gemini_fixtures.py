"""Scripted HTTP responses only; identifiers and keys are not production values."""
import json
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.schemas.ai_processing import FrozenSource, GenerationRequest

TEST_KEY = "fixture-key-not-a-production-secret"
TEST_MODEL = "gemini-fixture-model"


def config(**changes):
    return Settings(_env_file=None, ai_processing_provider="gemini", gemini_model=TEST_MODEL, gemini_api_key=TEST_KEY,
        ai_processing_timeout_seconds=2, **changes)


def request():
    body = 'Ana Marković nastupa 12. novembra 2026. Cena je 25 evra. Izjavila je: „Koncert počinje u 20 časova.“'
    return GenerationRequest(request_id=uuid4(), story_id=uuid4(), source=FrozenSource(article_id=uuid4(), source_id=uuid4(),
        source_name="Portal", source_url="https://source.invalid", external_id="1", original_url="https://source.invalid/article",
        canonical_url=None, language="sr-Latn", published_at=datetime(2026,11,1,tzinfo=timezone.utc), title="Koncert Ane Marković",
        excerpt="Ana Marković najavljuje koncert.", content=body, input_text=body, input_text_hash=hashlib.sha256(body.encode()).hexdigest(),
        captured_at=datetime.now(timezone.utc)))


def suggestion(req):
    return {"evidence_sufficient":True, "headline":"Ana Marković nastupa 12. novembra", "excerpt":"Cena ulaznice je 25 evra.",
        "lead":"Ana Marković najavljuje nastup.", "seo":{"title":"Nastup Ane Marković","description":"Najavljen nastup 12. novembra."},
        "body":'Ana Marković nastupa 12. novembra 2026. Cena je 25 evra. Izjavila je: „Koncert počinje u 20 časova.“',
        "source_references":[{"article_id":str(req.source.article_id),"source_id":str(req.source.source_id),
            "input_text_hash":req.source.input_text_hash,"excerpt":req.source.input_text[:200]}],"warnings":[]}


def envelope(req, **changes):
    return {"candidates":[{"finishReason":"STOP", "content":{"parts":[{"text":json.dumps(suggestion(req),ensure_ascii=False)}]}}],
        "modelVersion":"gemini-fixture-version-001", "responseId":"fixture-response-1",
        "usageMetadata":{"promptTokenCount":123,"candidatesTokenCount":70,"thoughtsTokenCount":7,"cachedContentTokenCount":0,"totalTokenCount":200}, **changes}


class ScriptedHTTP:
    def __init__(self, req, generate=None, metadata=None, count=None):
        self.req, self.generate, self.metadata, self.count = req, generate, metadata, count
        self.calls=[]

    def __call__(self, call):
        self.calls.append(call)
        if call.url.path.endswith(":countTokens"):
            return self.count(call) if self.count else httpx.Response(200,json={"totalTokens":123})
        if call.url.path.endswith(":generateContent"):
            return self.generate(call) if self.generate else httpx.Response(200,json=envelope(self.req))
        return self.metadata(call) if self.metadata else httpx.Response(200,json={"name":"models/"+TEST_MODEL,"version":"001",
            "inputTokenLimit":32768,"outputTokenLimit":8192,"supportedGenerationMethods":["generateContent","countTokens"]})
