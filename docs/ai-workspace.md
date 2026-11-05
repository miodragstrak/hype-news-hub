# AI editorial workspace — Sprint 17B.2A / 17B.2B

Open an existing story in the editorial queue, then choose **AI predlozi**.
The private route is `/review/:storyId/ai`. It reuses the verified identity
adapter, capability boundary, private HTTP client, navigation, pagination and
confirmation dialog from Sprint 17A. No production identity is activated.
Public collection, demo review and portal preview remain separate.

Readers can inspect source evidence and previous suggestions. Editors with enabled
editorial commands can explicitly generate one single-source `sr-Latn` translation
suggestion. Provider configuration and credentials remain entirely on the server.
Editors can open a successful suggestion in a separate acceptance editor. Review
decisions remain in the existing editorial workflow; publishing is unavailable.

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
- `POST /api/editorial/ai/suggestions/{id}/accept` with `command_id`, `story_id`,
  `expected_revision`, complete publishing `payload` and literal `confirm_acceptance: true`
- Existing draft lookup, exact immutable version detail and current draft reads
  confirm the accepted version and the separately observed current state.

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

## Editing and explicit acceptance — Sprint 17B.2B

Choose **Uredi i pripremi prihvatanje** after inspecting a successful suggestion.
The private, reloadable route is `/review/:storyId/ai/:suggestionId/edit`. It uses
the existing verified identity, Reader boundary plus Editor permission, publishing
form/validation and confirmation dialog. It needs a sealed suggestion and a
verified current draft lookup (404 means a new workspace), without fetching newer
source content. Unavailable or denied context cannot enable acceptance.

Headline, excerpt and body start from the saved AI output. Other publishing fields
reuse existing draft metadata if its schema is supported; a new workspace requires
the editor to enter slug, categories and SEO. Tags and images are optional. Image
references must use the single frozen source. Existing image references attributed
to another article require explicit correction; they are never silently removed.
Labels keep their structured, lossless representation. The original AI output,
warnings and evidence remain read-only and separate from the local publishing form.

Before freezing a command, scalar `Text` fields (headline, body, excerpt, SEO title/
description and image alt/credit) use the exact Pydantic boundary-whitespace set.
This includes U+0085, which JavaScript `trim()` misses; FEFF and internal whitespace
are preserved. Python's extra U+001C–U+001F separators remain invalid controls,
matching the actual backend validator. Category/tag padding requires explicit
editor correction so accepted labels remain lossless. Post-acceptance payload
verification remains exact, and recovery never renormalizes a frozen command.

Attribution is locked to the frozen article/source UUID pair. The server supplies
evidence, origin, provider provenance, authenticated actor and hashes; these are
never accepted from editable client metadata. Acceptance uses revision 0 for a new
workspace or the observed draft revision. `editing`, `changes_requested` and
`approved` permit a new version. `in_review` requires a review decision and `rejected`
requires reopening through the existing workflow. Already consumed suggestions
cannot be accepted again. An approved draft receives an editing version and loses
effective approval; historical decisions remain unchanged.

Review the complete form, then explicitly confirm **Prihvati u nacrt**. Each
confirmed command retains one UUID and the exact payload/revision. A synchronous
operation guard blocks duplicate clicks; inputs stay read-only during submission,
confirmation, context refresh or uncertain recovery. There is no automatic retry.
Cancellation or Escape restores the captured confirmation trigger after it becomes
enabled; confirmation does not move focus back to it. Existing dialog callers keep
their prior focus behavior unless they opt into the shared cancellation-focus ref.
An ambiguous POST keeps the original command for **Ponovi isto prihvatanje**.
After a valid receipt, recovery performs only reads, even if a detail response is
too large or unavailable. HTTP 409 preserves local edits and requires an explicit
context refresh and a new confirmation; that refresh never replaces local content.
401/403 removes private content and aborts pending operations.

Success is shown only after fetching the receipt's exact immutable version, a
fresh current draft and the suggestion's terminal accepted state. Version number, hash, `origin="ai"`, confirmed payload and
frozen evidence must match. A later concurrent edit cannot substitute current
content for the accepted version. Current status is explicitly labelled as observed
at the last read. Acceptance never approves or publishes content. Open the saved
draft to continue the existing manual editing/review workflow.

Unsaved changes and pending commands guard internal navigation and browser unload.
Local edits/command receipts remain page-memory only; logout or leaving clears
them. A refresh reloads the saved suggestion/state, not unsaved edits. If an uncertain
command may have completed, inspect history before starting another command; the
backend's terminal accepted state prevents consuming the suggestion twice.

With Node 22+ and Chrome, run `node frontend/tests/browser/ai-workspace.mjs`
from the repository root. It uses isolated browser fixtures and blocks real provider
traffic. It measures desktop/mobile wrapping, scroll regions and acceptance-dialog
bounds; it exercises keyboard scrolling, editing, explicit confirmation, cancellation,
version pinning, frozen evidence, same-command acceptance/generation recovery and
logout during generation. Optional
`AI_BROWSER_ARTIFACTS=/tmp/hnh-ai-browser` saves screenshots and measurements
outside the repository.

For the story-review entry, Ekavian lead/SEO output and durable daily limit, see [HNW-P0-01](ai-editorial-generation.md). Provider availability is now reported by private capabilities; absence/false disables new generation while history remains readable.
