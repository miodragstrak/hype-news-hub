# Private editorial queue (EQ-001)

`GET /api/editorial/queue?limit=20&offset=0` requires the existing verified
`editorial:read` permission and restricted PostgreSQL storage. Memory mode and
unconfigured identity verification fail closed. Successful responses use
`Cache-Control: no-store`. No AI provider is accessed.

The response contains `stories`, `stories_total`, `limit`, `offset`, `has_more`.
`limit` defaults to 20 (1–50); `offset` defaults to 0 (0–1,000,000). Stories without
article memberships are excluded, consistently with existing persisted story reads.
Ordering is persisted story publication time descending, nulls last, then story
UUID descending. This is intentionally not the public queue's dynamic importance
ranking. Existing intelligence scores, coverage, trend, risks and recommended
**advisory** actions are reused; a recommendation never authorizes publishing.

Each story retains the existing `EditorialQueueStory` fields and adds:

- `editorial`: null when no `sr-Latn` workspace exists, otherwise `draft_id`,
  actual editorial `status`, `revision`, `current_version_number`.
- `ai`: `has_suggestion`, `latest_suggestion_id`, `status`, `created_at`,
  `completed_at`, `recovery_required`. With no run these are false/null/false.

The inherited story `status` remains the collection projection. Editorial status
and AI processing status are separate. Latest AI means greatest `(created_at, id)`
for that story, including failed, interrupted, rejected and accepted records. It
does not mean latest successful or approved output. `recovery_required` means only
that the latest run is still `processing` with `expires_at <=` the UTC read time,
matching existing AI summaries. It neither grants recovery permission nor changes
that run. Original-actor recovery remains available through existing detail and
recovery contracts, unchanged.

The read uses the repository's restricted, repeatable-read, read-only transaction:
an exact count, a bounded story page with lateral latest-run lookup, and batched
source metadata loading for existing intelligence scoring. The existing AI
`(story_id, created_at, id)` index supports latest lookup. No migration or new grant
is required. Sealed input/output, actor identities, commands, AI events, article
bodies and raw source JSON are neither returned nor selected by this service.

Archive considerations: exact counts and deep offsets still cost work; source
memberships per story are not capped. Query count does not grow per story for the
bounded page, but work grows with its source memberships. Each response has a
consistent database snapshot; separate offset pages can move when collection
changes concurrently. Cursor pagination or precomputed scoring is future work.
The operational `/review` frontend uses this endpoint through the existing private
bearer/session transport. Explicit demo mode remains a separately labelled view
using demo/public projections; private access failures never fall back to it.
This endpoint is not a publishing or generation API.

Focused integration tests (use only the documented disposable PostgreSQL test DB):

```sh
cd backend
RUN_POSTGRES_TESTS=1 PYTHONPATH=.:tests python -B -m unittest \
  integration.test_editorial_queue test_private_editorial_queue -v
```

The existing public `/api/editorial-queue` route and schema are unchanged.

## Operational queue UI (EQ-002)

The compact queue displays publication time, source count and importance, with
separate collection, editorial and AI labels. A null editorial workspace is
"Nije započeto". An expired processing reservation is informational only; the
queue links to the existing protected AI workspace and never submits recovery,
generation, acceptance, approval or publishing commands.

Headline search and editorial/AI filters apply only to the loaded page. The UI
keeps the server archive total distinct from the filtered page count, and uses
`has_more` even when the last page is full. Filters reset when refreshing or
changing the page. State is a snapshot at load time; refresh explicitly for newer
changes. No queue content is stored in persistent browser storage. Pending reads
are aborted/ignored on navigation or identity changes. Failed reads clear visible
private rows and expose an explicit retry; unavailable private storage or identity
never triggers public/demo substitution.

Frontend verification (no live providers):

```sh
cd frontend
npm test
npm run typecheck
npm run build
npm run build:selfhosted
CHROME_NO_SANDBOX=1 node tests/browser/editorial-queue.mjs
```

The Chrome runner uses fixture responses at 1440×900, 390×844 and 320×568,
including a long unbroken headline, keyboard navigation, pagination, failure/retry
and logout. Omit `CHROME_NO_SANDBOX=1` when Chrome sandboxing is available.
Manual acceptance: log in as a Reader/Editor, open `/review`, apply each filter,
page forward/back, follow the story/AI links, refresh after an editorial change,
and log out during a pending read. No queue action should mutate a story or run.
