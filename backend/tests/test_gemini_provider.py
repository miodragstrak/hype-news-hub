import asyncio
import json
import unittest

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ai_provider import ProviderCancelled, ProviderConfigurationError, ProviderError
from app.services.gemini_provider import GeminiProvider, INSTRUCTIONS, MAX_RESPONSE_BYTES
from app.schemas.ai_processing import AI_REVIEW_WARNING
from gemini_fixtures import config, request, envelope, suggestion, ScriptedHTTP, TEST_KEY, TEST_MODEL


class GeminiProviderTests(unittest.IsolatedAsyncioTestCase):
    def setup_provider(self, **handlers):
        raw = request()
        http = ScriptedHTTP(raw, **handlers)
        provider = GeminiProvider(config(),transport=httpx.MockTransport(http))
        prepared = provider.prepare(raw)
        return provider, prepared, http

    async def test_structured_success_frozen_prompt_token_limits_and_usage(self):
        provider, req, http = self.setup_provider()
        result = await provider.generate(req)
        self.assertFalse(result.provenance.is_mock)
        self.assertEqual(result.provenance.provider,"gemini")
        self.assertIn(AI_REVIEW_WARNING,result.warnings)
        self.assertIn("25 evra",result.body)
        self.assertIn("12. novembra 2026",result.body)
        self.assertEqual(result.source_references[0].excerpt,req.source.input_text)
        self.assertEqual(req.instructions,INSTRUCTIONS)
        self.assertEqual(req.prompt_version,"sr-latn-translation-v1")
        generation = json.loads(http.calls[-1].content)
        counted = json.loads(http.calls[-2].content)["generateContentRequest"]
        self.assertEqual(counted,{"model":"models/"+TEST_MODEL,**generation})
        self.assertEqual(generation["systemInstruction"]["parts"][0]["text"],req.instructions)
        self.assertEqual(generation["generationConfig"]["maxOutputTokens"],2048)
        self.assertEqual(generation["generationConfig"]["responseJsonSchema"],json.loads(req.response_schema))
        self.assertNotIn("tools",generation)
        for call in http.calls:
            self.assertEqual(call.headers["x-goog-api-key"],TEST_KEY)
            self.assertNotIn(TEST_KEY,str(call.url))
            self.assertNotIn(TEST_KEY,call.content.decode())
            self.assertEqual(call.url.host,"generativelanguage.googleapis.com")
        self.assertEqual(result.metadata.usage.total_tokens,200)
        self.assertEqual(result.metadata.usage.thinking_tokens,7)
        self.assertEqual(result.metadata.counted_input_tokens,123)
        self.assertEqual(result.metadata.reported_model_version,"gemini-fixture-version-001")
        self.assertIsNone(result.metadata.estimated_cost)
        self.assertIsNone(result.metadata.pricing_provenance)
        self.assertNotIn("metadata",result.model_dump(mode="json"))

    async def test_missing_or_unsafe_model_configuration_is_local_and_no_network(self):
        for values in ({"gemini_api_key":""},{"gemini_model":""},{"gemini_model":"../../other"},
            {"gemini_model":"gemini-x?key=secret"},{"gemini_model":"https://untrusted.invalid"}):
            settings=config().model_copy(update=values)
            if "gemini_api_key" in values:
                from pydantic import SecretStr
                settings.gemini_api_key=SecretStr(values["gemini_api_key"])
            http=ScriptedHTTP(request())
            provider=GeminiProvider(settings,transport=httpx.MockTransport(http))
            with self.assertRaises(ProviderConfigurationError):provider.check_configuration()
            self.assertEqual(http.calls,[])
            with TestClient(create_app(settings)) as client:self.assertEqual(client.get("/").status_code,200)
        normalized=GeminiProvider(config().model_copy(update={"gemini_model":"models/"+TEST_MODEL}))
        self.assertEqual(normalized.provenance.model,TEST_MODEL)
        self.assertNotIn(TEST_KEY,repr(config()))

    async def test_unavailable_and_unsupported_models_never_generate(self):
        for handler in (lambda call:httpx.Response(404,json={"error":{"message":TEST_KEY}}),
            lambda call:httpx.Response(200,json={"name":"models/"+TEST_MODEL,"supportedGenerationMethods":["embedContent"]}),
            lambda call:httpx.Response(200,json={"name":"models/"+TEST_MODEL,"supportedGenerationMethods":"generateContent"})):
            provider, req, http=self.setup_provider(metadata=handler)
            with self.assertRaises(ProviderError) as error:await provider.generate(req)
            self.assertEqual(error.exception.code,"provider_invalid_model")
            self.assertEqual(len(http.calls),1)
            self.assertNotIn(TEST_KEY,str(error.exception))

    async def test_input_tokens_and_missing_body_fail_before_generation(self):
        provider, req, http=self.setup_provider(count=lambda call:httpx.Response(200,json={"totalTokens":4097}))
        with self.assertRaises(ProviderError) as error:await provider.generate(req)
        self.assertEqual(error.exception.code,"input_token_limit")
        self.assertEqual(len(http.calls),2)
        with self.assertRaises(ProviderError) as error:await provider.generate(req.model_copy(update={"source":req.source.model_copy(update={"content":None})}))
        self.assertEqual(error.exception.code,"insufficient_evidence")
        self.assertEqual(len(http.calls),2)

    async def test_refusal_incomplete_and_insufficient_evidence_keep_usage(self):
        for mode, code in (("refused","provider_refused"),("incomplete","provider_incomplete"),("insufficient","insufficient_evidence"),("retired","provider_invalid_model")):
            provider, req, http=self.setup_provider()
            data=envelope(req)
            if mode=="refused":data["promptFeedback"]={"blockReason":"SAFETY"};data["candidates"]=[]
            if mode=="incomplete":data["candidates"][0]["finishReason"]="MAX_TOKENS"
            if mode=="retired":data["modelStatus"]={"modelStage":"RETIRED"}
            if mode=="insufficient":
                content=suggestion(req);content["evidence_sufficient"]=False;content["warnings"]=["Nema dovoljno proverljivih podataka."]
                data["candidates"][0]["content"]["parts"][0]["text"]=json.dumps(content)
            http.generate=lambda call:httpx.Response(200,json=data)
            with self.assertRaises(ProviderError) as error:await provider.generate(req)
            self.assertEqual(error.exception.code,code)
            self.assertEqual(error.exception.metadata.usage.total_tokens,200)

    async def test_invalid_json_malformed_and_oversized_results(self):
        for response in (httpx.Response(200,text="<html>error</html>"),httpx.Response(200,content=b'\xff',headers={"Content-Type":"application/json"}),
            httpx.Response(200,content=b'{"candidates":NaN}',headers={"Content-Type":"application/json"}),
            httpx.Response(200,content=b'{"candidates":[],"candidates":[]}',headers={"Content-Type":"application/json"}),
            httpx.Response(200,json={"candidates":"bad structure"}),
            httpx.Response(200,content=b'x'*(MAX_RESPONSE_BYTES+1),headers={"Content-Type":"application/json"})):
            provider, req, http=self.setup_provider(generate=lambda call:response)
            with self.assertRaises(ProviderError) as error:await provider.generate(req)
            self.assertIn(error.exception.code,{"invalid_provider_output","provider_response_too_large"})
            self.assertEqual(len(http.calls),3)

    async def test_independent_schema_validation_rejects_bad_editorial_fields(self):
        for change in ({"body":"Текст на ћирилици"},{"body":"Ελληνικό κείμενο"},{"body":"日本語"},
                       {"headline":123},{"body":"<script>unsafe</script>"},{"warnings":["x"*501]}):
            provider, req, http=self.setup_provider()
            data=envelope(req)
            data["candidates"][0]["content"]["parts"][0]["text"]=json.dumps(suggestion(req)|change)
            http.generate=lambda call:httpx.Response(200,json=data)
            with self.assertRaises(ProviderError) as error:await provider.generate(req)
            self.assertEqual(error.exception.code,"invalid_provider_output")
            self.assertEqual(error.exception.metadata.usage.total_tokens,200)

    async def test_missing_language_and_date_add_truthful_warnings(self):
        provider, req, http=self.setup_provider()
        req=req.model_copy(update={"source":req.source.model_copy(update={"language":None,"source_language":None,"published_at":None})})
        result=await provider.generate(req)
        self.assertEqual(len(result.warnings),3)
        self.assertTrue(any("Datum" in warning for warning in result.warnings))

    async def test_throttling_is_retried_once_but_5xx_and_uncertain_post_are_not(self):
        provider, req, http=self.setup_provider()
        responses=[httpx.Response(429,json={"error":{"message":TEST_KEY}},headers={"Retry-After":"0"}),httpx.Response(200,json=envelope(req))]
        http.generate=lambda call:responses.pop(0)
        result=await provider.generate(req)
        self.assertEqual(result.metadata.generation_attempts,2)
        for status, code in ((429,"provider_throttled"),(403,"provider_auth"),(500,"provider_unavailable"),(503,"provider_unavailable"),(400,"provider_invalid_request"),(307,"provider_unavailable")):
            provider, req, http=self.setup_provider(generate=lambda call:httpx.Response(status,json={"error":{"message":TEST_KEY}},headers={"Retry-After":"0","Location":"https://other.invalid"}))
            with self.assertRaises(ProviderError) as error:await provider.generate(req)
            self.assertEqual(error.exception.code,code)
            self.assertEqual(len(http.calls),4 if status==429 else 3)
            self.assertNotIn(TEST_KEY,str(error.exception))
        def uncertain(call):raise httpx.ReadError("sensitive connection detail",request=call)
        provider, req, http=self.setup_provider(generate=uncertain)
        with self.assertRaises(ProviderError) as error:await provider.generate(req)
        self.assertEqual(error.exception.code,"provider_uncertain")
        self.assertEqual(len(http.calls),3)

    async def test_timeout_cancellation_and_predispatch_retry(self):
        def timeout(call):raise httpx.ReadTimeout("sensitive",request=call)
        provider, req, http=self.setup_provider(generate=timeout)
        with self.assertRaises(ProviderError) as error:await provider.generate(req)
        self.assertEqual(error.exception.code,"provider_timeout")
        self.assertEqual(len(http.calls),3)
        def cancel(call):raise asyncio.CancelledError()
        http.generate=cancel
        with self.assertRaises(asyncio.CancelledError):await provider.generate(req)
        attempts=0
        def connect(call):
            nonlocal attempts
            attempts+=1
            if attempts==1:raise httpx.ConnectError("not dispatched",request=call)
            return httpx.Response(200,json=envelope(req))
        http.generate=connect
        self.assertEqual((await provider.generate(req)).metadata.generation_attempts,2)

    async def test_overall_deadline_bounds_all_calls(self):
        async def hung(call):await asyncio.Future()
        provider=GeminiProvider(config().model_copy(update={"ai_processing_timeout_seconds":0.02}),transport=httpx.MockTransport(hung))
        with self.assertRaises(ProviderError) as error:await provider.generate(provider.prepare(request()))
        self.assertEqual(error.exception.code,"provider_timeout")

    async def test_cancellation_after_count_preserves_partial_metadata_without_retry(self):
        raw = request()
        http = ScriptedHTTP(raw)
        dispatched = asyncio.Event()

        async def transport(call):
            if call.url.path.endswith(":generateContent"):
                http.calls.append(call)
                dispatched.set()
                await asyncio.Future()
            return http(call)

        provider = GeminiProvider(config(), transport=httpx.MockTransport(transport))
        task = asyncio.create_task(provider.generate(provider.prepare(raw)))
        await dispatched.wait()
        task.cancel()
        with self.assertRaises(ProviderCancelled) as error:
            await task
        metadata = error.exception.metadata
        self.assertEqual(metadata.counted_input_tokens, 123)
        self.assertEqual(metadata.model_metadata_version, "001")
        self.assertEqual((metadata.http_attempts, metadata.generation_attempts), (3, 1))
        self.assertEqual(metadata.generation_outcome, "unknown")
        self.assertIsNone(metadata.usage)
        self.assertIsNone(metadata.estimated_cost)
        self.assertEqual(metadata.cost_status, "unknown")
        self.assertTrue(task.cancelled())
        self.assertEqual(len(http.calls), 3)

    async def test_absent_usage_is_unknown_and_invalid_counts_are_rejected(self):
        for usage in (None,{}, {"promptTokenCount":123}):
            provider, req, http=self.setup_provider()
            http.generate=lambda call:httpx.Response(200,json=envelope(req,usageMetadata=usage))
            result=await provider.generate(req)
            self.assertIsNone(result.metadata.estimated_cost)
            self.assertIsNone(result.metadata.usage.total_tokens if result.metadata.usage else None)
        provider, req, http=self.setup_provider()
        http.generate=lambda call:httpx.Response(200,json=envelope(req,usageMetadata={"totalTokenCount":-1}))
        with self.assertRaises(ProviderError) as error:await provider.generate(req)
        self.assertEqual(error.exception.code,"invalid_provider_output")
