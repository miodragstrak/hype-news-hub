# Gemini single-source provider — Sprint 17B.1C

The optional backend adapter implements the existing `generate(GenerationRequest)
-> GenerationResult` boundary using the installed httpx dependency. No SDK, agent,
tools, web retrieval, multi-source synthesis, frontend change or publishing is added.
The deterministic mock remains available and explicitly says it is not translation.
Gemini never falls back to mock or another model. Human acceptance and review remain
separate, authenticated PostgreSQL commands; generation never creates/approves a draft.

## Configuration and activation

| Backend environment variable | Default | Meaning |
| --- | --- | --- |
| `AI_PROCESSING_PROVIDER` | `disabled` | `disabled`, `mock`, or explicit `gemini` opt-in. |
| `GEMINI_MODEL` | empty | Reviewed, currently available text model ID; optional `models/` prefix. No model is hard-coded. |
| `GEMINI_API_KEY` | empty | Server-side SecretStr; never include in frontend/Vite settings, URLs, prompts or logs. |
| `AI_PROCESSING_TIMEOUT_SECONDS` | `5` | Overall seconds, maximum 30. Includes preflight, counting, reads and retry delays. Use 30 for a separately approved live check. |
| `GEMINI_MAX_INPUT_TOKENS` | `4096` | Tokenizer preflight limit; configurable 1–32768. Oversized input fails without generation. |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Sent as `maxOutputTokens`; configurable 1–8192, subject to model limits. |
| `GEMINI_SAFE_RETRIES` | `1` | Maximum safe retry per HTTP operation, 0 or 1. Set 0 for the first live check. |

Missing key/model or malformed model configuration does not prevent application
startup or public memory-mode operation. A new private processing command fails
with safe 503 and creates no request. Unknown/unavailable models discovered by API
preflight produce a durable `provider_invalid_model` failure, never a substitute.
Model identifiers in automated fixtures are fictional and must not be used live.

No production identity, secrets, Render/Vercel or Compose configuration was changed.
Compose does not forward these new Gemini settings; use a native Ubuntu backend
environment or a separately reviewed local override. The default application still
has an unconfigured identity verifier: an invented token cannot activate private AI.

## Frozen inputs, output and grounding

Preparation freezes the exact system instructions, prompt version
`sr-latn-translation-v1`, response JSON Schema and input/output token settings in
the existing immutable request JSON. Source UUIDs, original text, URLs, language
metadata and timestamps remain untouched. Mock request/output shapes and historical
hashes are preserved; old records are not rewritten. The adapter serializes this
frozen source, instructions and schema into Gemini's request; credentials are only
in the `x-goog-api-key` header.

The fixed TLS-verified Google REST endpoint is used with redirects and environment
proxies disabled. First `models.get` checks availability, generation support and
token limits. `countTokens` receives the complete generation request, including
system instructions/schema. Only then can one `generateContent` operation run.
Responses are limited to 256 KiB decoded JSON, with identity encoding required;
application input/output/detail budgets from [AI suggestions](ai-suggestions.md)
remain in force. No streaming or automatic continuation is used.

Structured output fields are `evidence_sufficient`, `headline`, `excerpt`, `body`,
one `source_references` entry and at most seven warnings. References contain the
exact article/source UUIDs, input-text hash and an original-language evidence
excerpt, not model-invented citation URLs. All wire fields are independently
validated. Missing/malformed fields, invalid UTF-8/Unicode, duplicate/non-finite JSON,
HTML, non-Latin editorial prose, oversized results or incomplete finish reasons fail.
Reference identity/hash/excerpt checks also run in the provider-independent service.
Generated HTTP(S) URL tokens are detected regardless of scheme capitalization
and must already occur byte-for-byte in frozen evidence/attribution; no URL
lowercasing, canonicalization or punctuation stripping changes their identity.

Absent source body fails conservatively before HTTP. The model can additionally
report insufficient evidence; no suggestion is saved in that case. Missing language
or publication date adds explicit warnings. Every successful result includes a
mandatory human-review warning. Original evidence excerpts may retain Cyrillic or
other scripts; generated prose must use Latin script.

Instructions require preserving names, dates, numerical values, quotations,
uncertainty and attribution. **These checks cannot prove factual entailment,
faithful quotation translation or Serbian-language quality.** Grounding annotations
are editorial assistance. One controlled local generation was reported successful
after acceptance; this is not a comprehensive quality evaluation or production
activation. Editors must compare original evidence before acceptance/review.

## Failure, retries and uncertain outcomes

| Situation | Safe processing error |
| --- | --- |
| Invalid/missing local configuration | HTTP 503 before reservation; no fallback. |
| Unavailable/unsupported model | `provider_invalid_model` |
| Invalid key/permissions | `provider_auth` |
| Exhausted HTTP 429 retry | `provider_throttled` |
| HTTP 5xx/service rejection | `provider_unavailable` |
| Unsupported request/schema | `provider_invalid_request` |
| Safety/refusal | `provider_refused` |
| Truncated/incomplete candidate | `provider_incomplete` |
| Missing body/model reports insufficient evidence | `insufficient_evidence` |
| Token preflight exceeds limit | `input_token_limit` |
| Malformed/unverifiable output | `invalid_provider_output` |
| Response-size limit | `provider_response_too_large` |
| Deadline/read timeout | `provider_timeout` |
| Ambiguous generation read/write failure | `provider_uncertain` |

At most one retry is permitted for explicit 429 rejection or connection/pool
failure before dispatch. Preflight operations can also retry transient 5xx once.
Retry delays are capped at one second and remain inside the overall deadline.
Generation 5xx, read/write failures, timeouts, malformed output and refusal are
never blindly retried. No SDK retry loop exists. Safety controls are not disabled.
If the API reports a legacy/deprecated/retired model status, its result is rejected.
Do not assume all metadata endpoints expose lifecycle status; review current model
availability/deprecation documentation before choosing the configuration.

Existing command-ID idempotency still prevents re-execution. An uncertain failed
request or expired/interrupted reservation is recovered with its original command,
not automatically generated again. A new command is an explicit new attempt and
may incur additional charges; investigate uncertain outcomes first. Cancellation
and process interruption cannot guarantee receipt of upstream usage or exactly-once
billing. Deadline cancellation and explicit cancellation preserve already-known
model metadata, token counts and dispatch state when the process can finalize its
record. Unreceived generation usage/cost remains unknown, even after dispatch.

## Accounting and provenance

Revision `20261101_06` adds `ai_processing_runs.processing_metadata`, bounded to
16 KiB, and additional safe error codes. It follows 05 without rewriting prior
migrations, adding tables or broadening runtime grants. Metadata is written once
at completion and remains immutable through acceptance/rejection. The request's
provider/model identity remains server-controlled; returned model version and
response ID are recorded separately.

`processing_metadata` records tokenizer input count, available prompt/output/thinking/
cached/total usage, metadata/reported model versions, response ID, HTTP/generation
attempt counts, outcome certainty, evidence sufficiency and output schema version.
Missing fields remain null rather than fabricated zeroes. Failure responses retain
usage when it was available, including refusal and invalid generated references.
Raw error bodies, safety details, headers and keys are never returned or persisted.

`estimated_cost` and `pricing_provenance` are explicitly null and `cost_status` is
`unknown`: no reviewed pricebook/model-tier billing configuration exists. Token
counts are not an invoice and no free-tier assumption is made. An accepted version's
editorial provenance links/copies this sealed metadata alongside its run hashes.

Downgrade 06 to 05 refuses non-mock requests or any recorded processing metadata,
because old code cannot represent Gemini provenance or accounting. Export/back up
and obtain a reviewed retention/recovery plan instead of dropping immutable history.
Legacy mock rows can round-trip without changing input/output hashes; 05's existing
accepted-receipt downgrade protection still applies.

## Automated verification

All provider traffic uses `httpx.MockTransport`; integration tests run against a
disposable PostgreSQL 16 database with an internal Docker network. No paid calls
are permitted during implementation. Tests cover payload/schema fidelity, limits,
invalid models/output/references, refusal/throttling, timeout/cancellation, safe
retry counts, missing keys, usage/unknown cost, restart/idempotency, metadata
immutability, migrations and existing acceptance/approval isolation.

## Controlled live check — only after review and explicit spending approval

1. Choose a currently available structured-output text model for the intended
   account using the official model documentation/API. Do not copy a fixture ID.
2. Use a local environment and protected environment variables, never production
   settings. Enter the key without shell-history exposure. Start with input limit
   2048, output limit 1024, overall timeout 30 and `GEMINI_SAFE_RETRIES=0`.
3. Prepare a small, approved public source snapshot as a `GenerationRequest` JSON
   file outside the repository. Inspect the exact content and exclude sensitive
   material. Keep the key out of that file.
4. A standalone operator probe can test the adapter without activating any HTTP
   identity bypass or modifying editorial/database state. **The following calls
   the provider and may incur charges; it was not executed during implementation:**

```python
import asyncio
from pathlib import Path
from app.core.config import Settings
from app.schemas.ai_processing import GenerationRequest
from app.services.gemini_provider import GeminiProvider

provider = GeminiProvider(Settings())
frozen = GenerationRequest.model_validate_json(Path('/tmp/approved-source.json').read_text())
prepared = provider.prepare(frozen)
# Inspect prepared source, instructions and limits before the next line.
result = asyncio.run(provider.generate(prepared))  # explicit paid-call boundary
print(result.model_dump_json())
print(result.metadata.model_dump_json() if result.metadata else 'Usage unknown')
```

5. Compare Serbian Latin wording, names, dates, numbers, quotations, attribution
   and warnings with the source. Check reported usage and vendor billing; cost
   estimation is still unknown. Stop after one generation, including on failure.
6. An end-to-end persisted API check additionally requires an already approved
   verified local identity integration. Default private routes must remain closed
   without it. Use one command ID, inspect the durable result and retry only that
   original command on an uncertain response. Do not accept, approve or publish
   automatically. Production identity activation remains outside this sprint.

Official references (checked 2026-11-01): [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output),
[REST generation/usage metadata](https://ai.google.dev/api/generate-content),
[model discovery](https://ai.google.dev/api/models), [token counting](https://ai.google.dev/api/tokens).
