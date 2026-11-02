# Persisted AI suggestions, human acceptance and optional Gemini — Sprint 17B

This backend phase supports one persisted story article, translation mode and
`sr-Latn` only. Its deterministic **mock does not translate**, verify facts or
produce publication-ready news. Every mock result includes `is_mock: true`, provider
`mock`, model `deterministic-no-translation-v1`, adapter/prompt versions and an
explicit Serbian demo warning. Explicit human acceptance can now save an editing
version through the existing editorial command service. Sprint 17B.1C adds an
optional [Gemini adapter](gemini-provider.md), disabled by default, with frozen
prompts, bounded HTTP/token use and sealed accounting. No credentials, frontend or
publishing integration are added; no live calls were made during implementation.

## Two-table design

Revision `20261101_04` follows `20261030_03`; earlier migrations are unchanged.
Revision `20261101_05` follows 04 and adds acceptance references, receipt storage
and integrity guards without rewriting 04 or introducing more tables.
Revision `20261101_06` adds sealed processing metadata and provider error codes;
04/05 remain unchanged. See [Gemini operations](gemini-provider.md).

| Table | Responsibility | Runtime rights |
| --- | --- | --- |
| `public.ai_processing_runs` | Stable request UUID, global command UUID, verified creator, story/article/source UUIDs, immutable input JSONB and provenance, state/revision, sealed validated output, hashes, safe error codes and deadlines. | SELECT, INSERT, UPDATE |
| `public.ai_processing_events` | Append-only request/completion/rejection/acceptance history, verified actor, command hash, optional rejection reason and immutable acceptance receipt. | SELECT, INSERT |

Embedding one source snapshot in the run avoids a third table and a separate
snapshot-completeness protocol. The snapshot has direct article/source composite
foreign keys plus story FK and JSON identity checks. Application validation checks
story membership in the same query that captures article/source data. Immutable
input is the complete `GenerationRequest` object actually passed to the provider,
including original title/excerpt/content, exact assembled input text, source name,
external ID, original/canonical URLs, separate article/source language metadata,
available publication metadata and capture time. No language is guessed or source content translated in storage.
Text is already collected/normalized data, not byte-exact original website HTML.

The input text SHA-256 covers its exact UTF-8 bytes; the database-generated input
and output hashes cover PostgreSQL's canonical JSONB text representation. A source
may have the same external WordPress ID as another portal; only stable UUID pairs
are accepted. No API accepts caller-supplied evidence, provenance, roles or actors.

Database triggers protect request/evidence/provenance and sealed results. Every
state revision requires a corresponding event in the same transaction; event
updates/deletes and run deletes are blocked. The existing runtime guard also covers
both tables, including excessive table/column grants, PUBLIC grants and ownership.
There is no automatic cleanup/retention or generalized queue. A normalized evidence
table may be appropriate when multi-source synthesis is introduced; retain this
schema's frozen inputs rather than rewriting historical requests.

## Local preparation and activation boundary

Use the existing dedicated PostgreSQL 16 workflow in [PostgreSQL operations](postgresql.md):

```bash
docker compose --profile tools run --rm --build migrate
docker compose --profile tools run --rm --build provision-runtime
```

Back up first and run these with protected migration-owner credentials. Existing
runtime logins **must be re-provisioned after upgrading** to receive the two new
table allowlists. PUBLIC/delegated grant remediation remains an administrator task;
provisioning does not silently modify unrelated roles or shared ACLs.

Native Ubuntu development may set `AI_PROCESSING_PROVIDER=mock` and
`AI_PROCESSING_TIMEOUT_SECONDS=5` in the backend process environment. The only
provider values are `disabled` (default), `mock` and explicit `gemini` opt-in. Compose,
Render and Vercel settings are unchanged, and Compose does not forward these new
opt-in settings. A production identity verifier is still unconfigured. Integration
tests inject the existing test-only verifier and mock provider; there is no runtime
test-token switch or development authentication bypass. Memory mode cannot execute
private AI operations, including when the mock is enabled. Public routes stay usable.

## API contracts

Base path: `/api/editorial/ai/suggestions`. All responses are private/no-store on
successful authorization. Existing editorial/public endpoints are unchanged.

| Method/path | Permission | Contract |
| --- | --- | --- |
| POST base | Edit | `command_id`, `story_id`, `article_id`, `source_id` UUIDs; `mode: translation` and `target_locale: sr-Latn` default to their only supported values. Returns full `SuggestionRead`. |
| GET base `?story_id=UUID` | Read | Lightweight `SuggestionSummary[]`; default limit 20, maximum 50; offset 0–1,000,000. No evidence, output body or event loading. |
| GET `/{id}` | Read | Complete frozen input, validated output if present, hashes, provenance, status, timestamps, creator and at most three events. |
| POST `/{id}/reject` | Edit | `command_id`, strict positive `expected_revision`, required reason (maximum 2,000 characters); only a successful revision 2 can become rejected revision 3. |
| POST `/{id}/accept` | Edit | `command_id`, intended `story_id`, strict nonnegative `expected_revision`, complete `PublishingPayload`, and literal JSON `confirm_acceptance: true`; 200 `CommandResult`. |

POST creation returns 201 when the new processing resource has finished, 202 when
an identical request is still processing, or 200 for a completed/recovered retry.
**201 does not mean generation succeeded:** inspect `status` and `error_code`.
Provider failures are durable resources, with no output accepted as a suggestion.
Errors use 401/403 for authentication/permission failures, 404 for missing reads,
409 for command/state conflicts, 422 for invalid source membership or size limits,
and 503 for disabled processing or unavailable/misconfigured storage/identity.
The shared 1 MiB request boundary safely rejects malformed JSON/non-finite numbers
(400), unsupported media/charsets (415) and oversized requests (413), without
reflecting raw input. Rejected validation requests create no records.

## Processing, retry and recovery

`SuggestionProvider.generate(GenerationRequest) -> GenerationResult` is async and
application-owned. Mock dependencies can be replaced in tests without exposing
provider selection, credentials or URLs to clients. Output must satisfy bounded
plain-Latin headline/excerpt/body schemas. Its sole source reference must match
the selected UUID pair, input-text hash and an exact nonempty excerpt of frozen
input. Provider provenance and the explicit no-translation warning are mandatory.
Original-language excerpts remain untouched, including Cyrillic. These checks
establish reference integrity, not factual entailment or translation quality.

1. A short transaction reserves the command and freezes evidence with status
   `processing`/revision 1 and a request event. A transaction-scoped PostgreSQL
   advisory lock serializes the global command UUID across processes/containers.
2. The transaction commits before provider invocation. There are no background
   tasks, long-running generation transactions or automatic service-level regeneration.
   Gemini's bounded safe HTTP retries are documented in [provider operations](gemini-provider.md).
3. A second transaction seals `succeeded`, `failed` or `interrupted`/revision 2
   and its event atomically. Output remains unchanged if later rejected or accepted.

The same command ID, payload and verified identity reuse the same record, including
after rejection, acceptance or provider disablement. Changed payload/identity/action under
that key returns 409. The API never executes a duplicate reservation again.

Provider timeout, failure and invalid output become sanitized `provider_timeout`,
`provider_failure` and `invalid_provider_output` error codes. No exception text,
invalid result body or credentials are stored or returned. If a worker stops or
finalization cannot commit, its reservation survives. After the provider deadline
plus five seconds, reads advertise `recovery_required: true` without writing.
An identical POST retry seals it as `interrupted`/`process_interrupted`; it does
not regenerate. Late results cannot revive that request. An explicit new command
ID starts a new attempt and captures current source data. Keep the original
command ID/payload until its uncertain outcome is resolved.

Limits: 64 KiB UTF-8 assembled source text, 256 KiB frozen JSON input, 64 KiB
validated output, 512 KiB detail response; oversize values are rejected, never
silently truncated. Provider timeout defaults to 5 seconds (maximum 30). The mock
only quotes a bounded excerpt for its reference; complete input remains available.
Mock execution claims no model usage. Optional Gemini records reported usage and
explicitly unknown estimated cost; see [accounting policy](gemini-provider.md#accounting-and-provenance).

Generation, failures and rejection never write editorial tables or approval state.
Suggestion rejection is not an editorial review decision.

## Explicit acceptance into an editorial version

The complete confirmed payload uses the existing [publishing schema](editorial-workflow.md).
Its sole attribution must match the suggestion's frozen article/source UUID pair.
Editors can change the suggested wording and supply validated slug, categories,
tags, SEO and image references; source attribution cannot be replaced or expanded.
Origin, hashes, provider metadata, actors and evidence are never caller-controlled.
Missing/false/non-boolean confirmation, invalid payload and mismatched attribution
return 422. Unknown suggestions return 404. Wrong story, consumed/unfinished
suggestion, stale revision or a disallowed editorial state returns 409.

Use expected revision 0 only when no workspace exists. A positive expected revision
must match the current workspace. The existing editable states are `editing`,
`changes_requested` and `approved`; `in_review` requires its normal review decision,
and `rejected` must first be reopened. Acceptance always writes a new immutable
version with `origin="ai"` and status `editing`, including when its confirmed payload
matches the previous payload. It never approves content. Historical versions and
decisions remain immutable; any previous effective approval is invalidated.

One transaction locks the AI command, suggestion and story/locale workspace, then
uses the shared editorial writer (`write_payload`, `add_version`, CAS and audit)
for either draft creation or a new version. It copies source identity, original and
canonical URLs, publication time, captured input text and capture timestamp directly
from the sealed run, never from refreshed collected content or prior draft evidence.
The complete original excerpt/body and article/source language metadata remain in
the immutable run. The paired `draft.accept_ai` event records the suggestion ID,
input/output/text hashes, provider/model/adapter identity, prompt version, known
publishing schema version, language metadata, verified accepting actor and timestamp.
No generation schema version is invented for older runs that did not record one.

The suggestion changes from successful revision 2 to terminal `accepted` revision 3;
rejection and acceptance are mutually exclusive. Its accepted draft/version/content
hash have a composite FK. Deferred database guards additionally require the exact
source snapshot and matching AI/editorial receipts, actor and timestamp. The paired
AI acceptance event stores the existing `CommandResult`, visible in private detail
history as `events[].result` (null for other events). Private AI status enums add
`accepted`; existing collection/manual editorial schemas and endpoints are unchanged.

Retry the identical command/payload/identity after a lost response or restart to get
the original receipt without another version. A receipt describes that command's
revision, not the draft's current state: read the draft for current content/effective
approval. Another command cannot accept an already accepted suggestion. Reused keys
with changed payload, identity, action or suggestion return 409. Concurrent manual
saves/acceptances use the same expected-revision protocol; either operation can win.
Any intermediate failure rolls back draft, version, snapshots, events and AI state.
Acceptance needs verified identity and PostgreSQL but no enabled provider.

## Verification and migration recovery

Run the standard Python 3.12/PostgreSQL 16 suite using the dedicated disposable
`hype_news_hub_test` instance; no production database is accepted by its fixtures:

```bash
docker compose --profile test up --build --abort-on-container-exit --exit-code-from database-tests database-tests
```

Tests cover restart/command recovery, two independent applications, immutable
evidence after recollection, invalid/foreign references, output failures, timeout,
rollback, bounded history reads, role restrictions and unchanged effective approval.
Migration checks include clean install, downgrade/re-upgrade, Alembic model comparison
and preservation of populated collection/editorial data.
Acceptance regressions additionally cover workspace creation, approval invalidation,
concurrent accept/accept and accept/reject races, manual-save conflicts, lost responses,
restart receipts, injected rollback and database rejection of refreshed evidence.

Downgrade 05 to 04 is refused if any accepted suggestions exist: 04 cannot represent
their immutable receipts, and rollback must not silently remove provenance. Back up/
export and obtain an explicit administrator-reviewed retention/recovery plan first.
When no accepted suggestions exist, 05 downgrades reversibly and preserves existing
AI, editorial and collection data. Owner maintenance of referenced editorial tables
must account for the AI-to-version FK; no runtime DELETE/TRUNCATE is granted.

After an allowed downgrade to 04, downgrading to `20261030_03` **deletes all AI requests, evidence, suggestions and
events**, while retaining existing collection and editorial data. Export/back up
before an explicitly reviewed downgrade; restore a backup to recover deleted AI
history. Do not rewrite any previously applied revision.

## Next phase

Gemini implementation is complete, and one controlled local generation was reported
successful after acceptance. Production activation still requires separate review,
model evaluation and protected credentials. A single successful call does not
establish translation quality or factual correctness. Sprint 17B.2A adds the
[generation and review workspace](ai-workspace.md); suggestion acceptance/editing
in the frontend and multi-source input remain later work.
