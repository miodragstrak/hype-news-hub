# AI editorial workspace — Sprint 17B.2A

Open an existing story in the editorial queue, then choose **AI predlozi**.
The private route is `/review/:storyId/ai`. It reuses the verified identity
adapter, capability boundary, private HTTP client, navigation, pagination and
confirmation dialog from Sprint 17A. No production identity is activated.
Public collection, demo review and portal preview remain separate.

Readers can inspect source evidence and previous suggestions. Editors with enabled
editorial commands can explicitly generate one single-source `sr-Latn` translation
suggestion. Provider configuration and credentials remain entirely on the server.
No acceptance, revision editing, review decision or publishing command is exposed.

The comparison stacks on mobile and uses two columns at desktop widths. Content
is plain text, with keyboard-focusable scroll regions for long articles. Source
URLs use the existing HTTP(S) link policy; external HTML is never rendered as HTML.
Provider/model identity, mock disclosure, warnings, source UUIDs, hashes, references,
available usage and explicitly unknown cost are displayed with the saved result.

## Existing API contracts

The workspace uses private capabilities, source summaries and draft lookup, plus:

- `GET /api/editorial/ai/suggestions?story_id=...&limit=20&offset=0`
- `GET /api/editorial/ai/suggestions/{id}` only when selected
- `POST /api/editorial/ai/suggestions` with a fresh command UUID, story/article/source
  UUIDs, `mode=translation` and `target_locale=sr-Latn`

History page sizes are 5/10/20/50. Source summaries load in pages of 50. No new backend
endpoint, migration, dependency or deployment setting is required.

The private source-summary endpoint omits body and language. The existing
`GET /api/editorial-stories/{storyId}` supplies current collected text. It is read
through the private client's no-store transport, without demo fallback. Full text
is shown only for a unique portal URL plus original/canonical article URL match;
shared external WordPress IDs are never used to select an article. Missing or
ambiguous matches show a truthful unavailable message. Generation still selects
the authoritative persisted UUID pair, and may capture newer collection data.

Selecting a saved suggestion always replaces the comparison's original side with
that run's exact frozen evidence. Current article data never fills missing frozen
IDs, language, dates or content. A null frozen external ID displays "Nije dostupan".
Draft status is labelled as observed when the context was loaded;
generating suggestions does not update or imply approval.

History loads independently of current-story, source-list and draft-status reads,
including while those reads are pending. Optional failures show explicit warnings;
sealed suggestions and history pagination remain available. Generation and command
recovery stay disabled until current context and permissions are verified. Draft
404 confirms that no draft exists; other failures never imply a missing draft.
Context can be reloaded explicitly with GETs without replacing selected frozen
evidence or replaying a generation command. Any 401/403 invalidates all private
views and pending requests, regardless of which read failed.

## Reliability and boundaries

History/detail operations and commands remain serialized; optional context reads
run separately with cancellation guards. A synchronous guard prevents rapid
double-clicks from creating duplicate commands. HTTP 201 means a resource was
created; only its validated status/output determines whether a suggestion succeeded.
Failed, interrupted, processing, rejected and accepted historical states stay distinct.

An ambiguous response retains the exact command in page memory and blocks a new
generation. There is no automatic retry or polling. Users can read history or
explicitly confirm recovery with the original command and payload. If the server
already reserved it, backend idempotency prevents regeneration; if it never arrived,
the confirmed recovery may start processing and incur cost. Expired reservations
follow the existing interrupted-recovery semantics. Navigation/unload warns about
pending or unconfirmed commands; note the displayed command ID before leaving.

The existing capability endpoint does not advertise AI provider readiness. The UI
cannot promise Gemini availability before an explicit request. HTTP 503 reports
unavailability and retains an uncertain command rather than assuming it was never
processed. No provider or model fallback is introduced.

Private content and recovery commands are never written to local/session storage,
public demo context or public preview state. Logout, identity replacement, denied
access and story navigation unmount/abort the workspace; late responses cannot
restore it. Reopening reloads persisted suggestion history. An unacknowledged
command ID is intentionally not persisted across browser refresh.

## Verification

Run `npm test`, `npm run typecheck` and `npm run build` from `frontend/`.
Tests use scripted HTTP and the isolated test identity adapter, covering generation,
uncertain responses, same-command recovery, failure/unavailable states, UUID source
selection, lazy history, frozen evidence, authorization and private-state isolation.
No live Gemini calls are part of frontend verification.

With Node 22+ and Chrome, run `node frontend/tests/browser/ai-workspace.mjs`
from the repository root. It uses isolated browser fixtures and blocks real provider
traffic. It measures desktop/mobile wrapping and scroll regions, exercises keyboard
scrolling, same-command recovery and logout during generation. Optional
`AI_BROWSER_ARTIFACTS=/tmp/hnh-ai-browser` saves screenshots and measurements
outside the repository.
