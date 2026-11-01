# Private editorial frontend — Sprints 17A.3A and 17A.3B

The existing React/Vite newsroom now has a private draft editor at
`/review/{story_id}/edit`. The public queue and Review preview show capability-aware
entry points. Collect, Process, publishing previews and portal previews retain their
existing public contracts and demo behavior. Authenticated history, review decisions
and approved preview use separate private routes. AI generation and WordPress
delivery remain unavailable.

## Composition and authentication

`App` accepts an optional `editorialIdentity: EditorialIdentityAdapter`. The default
is unconfigured: public pages continue working and the editor truthfully reports
that production editing is unavailable. There is no token input, browser-storage
token setting, environment credential, fake login, client role selector or global
development authentication switch.

A future trusted identity SDK adapter must implement:

```ts
interface EditorialIdentityAdapter {
  getSnapshot(): { readonly key: string } | null;
  subscribe(listener: () => void): () => void;
  getAccessToken(): Promise<string | null>;
}
```

Snapshots must have stable object identity until the SDK session changes. The
opaque, nonsecret `key` identifies a local session lifecycle, not an API actor.
Keep the key stable across access-token refresh and rotate it on logout/login or
identity change. Notify subscribers when session state changes. The SDK owns token
acquisition/refresh; never map unverified browser claims into application roles.
The actual backend independently verifies every Bearer credential and constructs
actors/permissions. The browser uses only returned capabilities for presentation.

Compose the adapter into `<App editorialIdentity={trustedSdkAdapter} />` in the
data-router root once production identity integration is separately approved.
`main.tsx` uses `createBrowserRouter`/`RouterProvider` so unsaved-change blockers
work for links and Back/Forward. Tests use `createMemoryRouter`. Backend identity
verification and restricted PostgreSQL must also be configured; a frontend adapter
alone cannot activate backend commands. No production adapter/credentials or
Render/Vercel configuration are added in this sprint.

`EditorialAccessProvider` keeps capability metadata separate from public
`DemoDataContext`. Tokens are acquired per request, never persisted or logged.
Private fetches use `Authorization: Bearer`, omitted cookies, no-store caching,
rejected redirects, abort signals and a 60-second HTTP deadline. The same session
is checked before and after token acquisition. Identity changes/logout clear the
route-local private workspace and prevent late requests from restoring its UI.
Same-session token refresh preserves local edits. A session becomes usable only
after its SDK change subscription succeeds. Subscription, snapshot and token
acquisition failures disable private access and unmount its workspace. Old SDK
callbacks and tokens cannot restore it. Recovery requires an explicit access retry
or a replacement adapter with a working subscription. Observed logout/login
boundaries invalidate old requests even if the SDK reuses a session key. Public
pages remain usable.

## API client and contracts

`types/editorial.ts` mirrors the actual backend capability, source, draft, payload
and receipt schemas. `services/editorialApi.ts` calls only:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/editorial/capabilities` | Verified storage/permissions/command availability |
| GET | `/api/editorial/stories/{story_id}/sources?limit=50&offset=…` | UUID-based source selection |
| POST | `/api/editorial/drafts` | Manual sr-Latn creation, expected revision zero |
| GET | `/api/editorial/drafts?story_id=…` | Find saved workspace after navigation/refresh |
| GET | `/api/editorial/drafts/{id}` | Current version, revision, state and frozen evidence |
| POST | `/api/editorial/drafts/{id}/revisions` | Complete payload replacement at expected revision |
| GET | `/api/editorial/drafts/{id}/versions?limit=20&offset=…` | Lightweight metadata, default 20 / maximum 50 |
| GET | `/api/editorial/drafts/{id}/versions/{version_number}` | One complete immutable version and frozen evidence |
| GET | `/api/editorial/drafts/{id}/events?limit=20&offset=…` | Paginated private audit timeline |
| POST | `/api/editorial/drafts/{id}/submit` | Submit the exact current version for review |
| POST | `/api/editorial/drafts/{id}/approve` | Reviewer approves the exact submitted version |
| POST | `/api/editorial/drafts/{id}/request-changes` | Reviewer requests changes with reasoning |
| POST | `/api/editorial/drafts/{id}/reject` | Reviewer rejects with reasoning |
| POST | `/api/editorial/drafts/{id}/reopen` | Editor reopens rejected/requested changes with reasoning |

The current-draft response already includes its complete current version and
snapshots. Resolving a story-only route therefore transfers that current version
once; the history list itself contains no payload or evidence. Historical detail
requests occur only on explicit selection, with no per-row fetches. See
[backend workflow contracts](editorial-workflow.md).

Verified Read access permits private inspection; Edit plus enabled commands permits
creation/saving. In-review and rejected drafts remain read-only. Editing an approved
draft carries an explicit notice that the new version invalidates its approval.
Explicitly enabled public demo mode cannot create production editorial drafts.

## Navigation, review and immutable previews

`EditorialNavigation` connects the public queue, `/review/{story_id}/edit`,
`/review/{story_id}/history`, `/review/{story_id}/decisions` and
`/review/{story_id}/approved`. New workflow views use Serbian Latin labels and
the existing Hype styles. A capability-aware entry on public Review leads directly
to decisions. Reader permission protects every private view; client role controls
are presentation only and never replace backend authorization.

History and audit lists retain one page at a time, with 5/10/20/50-entry choices
and offsets bounded by the existing API. They do not invent a total count. Version
summaries preserve IDs, numbers, authorship, hashes, timestamps and source counts.
Selecting a version loads its immutable payload and snapshots only. Budget failures
(256 KiB summaries / 32 MiB details) produce an error instead of truncation. The
source viewer renders frozen input as text; it never enriches historical versions
with current collection content. Legacy payloads have a read-only JSON view.

The decisions page previews the saved server version, not the editor's unsaved
form. Editor permission enables reopen; Submit permission enables editing →
in_review. Reviewer permission enables in_review → approved / changes_requested /
rejected. An Editor can continue requested changes by saving a new revision, or
reopen requested/rejected content through the backend's existing command. All
actions require confirmation bound to version number, hash and expected revision.
Request-changes, reject and reopen require plain Latin reasoning (maximum 2000
characters); approval reasoning is optional. Submit has no reason field.

Commands retain their exact UUID/body during uncertain outcomes. A receipt is
followed by a fresh draft read; a failed confirmation retries GET only. A historical
receipt never overwrites current status or reactivates an old approval. Conflicts
keep local reasoning, pause decisions, and require an explicit latest-state read
before a new confirmation. Reason text stays route-local until a command records
it; navigation/unload warnings protect unfinished work. Audit records show the
server-authenticated actor, action, state transition, version, reason, command ID
and timestamp. History is never edited or deleted by the frontend.

Approved preview resolves `status=approved` plus `effective_approval=true` from a
fresh head, loads the exact immutable version endpoint, verifies ID/number/hash,
then rereads the head before displaying anything as approved. It never reads local
editor state or public preview packages. Approval actor/time are shown only when
an event receipt matches the exact draft/revision/version/hash. Metadata lookup is
bounded to the first 50 events; absent metadata is disclosed and the paginated audit
timeline remains available. Historical approval rows alone cannot enable preview.

An approved preview is a verified point-in-time snapshot, not a live publishing
authorization. It rechecks the head on focus/visibility and every 30 seconds while
visible. During verification/errors/hidden-tab state the approved content is hidden.
A changed pin is cleared; a different approved version requires explicit loading.
Remote changes can occur between checks because there is no server push endpoint.
The existing head response contains full current evidence, so periodic checks have
that transfer cost. Future delivery must reauthorize approval in its own server
transaction. WordPress publishing is visibly disabled and makes no network calls.

`EditorialPrivatePage` unmounts all its private children on 401/403 or identity loss.
Operation tickets and abort signals prevent late reads/commands from restoring
content. No identity credentials, development bypasses, new endpoints, migrations
or deployment settings are introduced.

## Form, evidence and privacy

The form includes headline/body/excerpt/slug, category/tag labels (one per box),
SEO fields and up to ten image references with URL, alternative text, credit and
selected source article UUID. The first image is presented as featured; existing
additional references are retained. Image URLs are references only and are not
downloaded by this editor. The server remains authoritative for URL safety,
Unicode edge cases and all publishing constraints.

Category/tag arrays remain structured values throughout loading, editing and
saving. Newlines, CRLF, commas, tabs and other valid characters inside a label do
not split it into additional labels. An untouched label is sent exactly as stored,
even when a textarea displays CRLF as LF. Add/remove controls change individual
array entries explicitly. Empty labels and outer whitespace that the backend would
strip require explicit correction; saving never silently trims existing labels.

Each source selection sends an article UUID/source UUID pair. Source pages load
incrementally. Existing selected snapshots remain available when their current
summary is outside the loaded page. Shared external WordPress post IDs never
determine selection. The public Review preview also uses a composite portal/URL/ID
key so two portals' posts do not collide in its source picker.

The evidence pane clearly separates current source metadata/excerpts from frozen
input. Full current text is optional and fetched through the existing public
workspace endpoint. Because that public contract has no article UUID, enrichment
requires a unique matching portal URL and original/canonical article URL; ambiguous
or changed URL aliases show an unavailable message instead of guessing from post
IDs. Saved snapshots retain their exact input, capture timestamps and hashes.
All external text is rendered as React text, never rich HTML. Source links allow
HTTP(S) without userinfo; remote images/HTML are not embedded in the private editor.

Drafts, form values, frozen evidence, comparison data and pending commands exist
only in the private route's React state. They are never copied into public demo
packages, navigation state, localStorage, sessionStorage or a global query cache.
No local unsaved-content recovery across reload/crash is provided. Public publishing
and portal previews continue using public/demo packages only.

## Save, retry and conflict behavior

Only explicit Save sends a command. Client validation catches common field, script,
source and image-reference errors. Unchanged normalized content creates no request.
Each new intent receives a cryptographic UUID. Existing drafts send the loaded
expected revision; creation sends zero. Save inputs are frozen while the result
is uncertain, so retry preserves the exact command ID, payload and revision.

Save, reload and comparison share a synchronous operation lock. A confirmed reload
freezes inputs and command controls until it succeeds or fails; a failed read keeps
the original local text and dirty state. Each response must still own its operation
and active page lifetime. Reload additionally checks the local input revision before
replacing anything. Navigation/logout aborts the page's requests and invalidates
their operation ownership, so delayed responses cannot update a revisited editor.

A server receipt is followed by a fresh private draft read. The UI confirms success
only when the current version/hash and payload agree with that receipt. If only
the read fails, confirmation retries GET without repeating POST. A newer content
version yields a conflict instead of replacing local text. A state-only advance
with the same version/hash is shown with its fresh server state.

On 409, local input remains visible and saving pauses. Compare loads server data
separately; only an explicit, confirmed reload replaces local edits and obtains
the new expected revision. No automatic rebase or forced overwrite is performed.
Known validation failures allow correction; network/5xx/timeout uncertainty keeps
the original command for retry. Responses never reflect raw backend error bodies.
401/403 clear private content and require renewed access verification.

Dirty or unconfirmed work triggers a keyboard-accessible in-app navigation dialog
and a browser refresh/close warning. Unmounting aborts browser requests but cannot
guarantee cancellation of a server transaction; the dialog discloses this. Reloading
or revisiting always queries PostgreSQL-backed state instead of assuming a receipt
or local package is current.

## Verification and remaining work

Frontend tests cover real request shapes, capability failures, read-only access,
create/save/reload, conflicts, exact retries, dropped confirmation reads, logout,
same-session refresh, subscription initialization failures, adapter replacement,
late tokens, delayed reload/save races, lossless metadata round-trips, validation, duplicated external IDs,
plaintext evidence and public-state separation. Existing public regression tests
remain part of the suite. A temporary Chrome harness with an isolated FastAPI test
identity and disposable PostgreSQL also verifies create/save/reload and desktop/
mobile layouts; neither the harness nor its identity is shipped in the application.

Remaining work: production frontend/backend identity adapters, broader browser UAT,
explicit frozen-evidence refresh and WordPress delivery. Source URL aliases can make optional full-current-text
enrichment unavailable. Manual editing/factual review remains human work; there is
no automatic Serbian translation or AI generation.
