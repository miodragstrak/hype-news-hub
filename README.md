# Hype News Hub

Internal application for aggregating and processing entertainment news.

## Sprint 15A: PostgreSQL foundation

The initial schema and local/private PostgreSQL tooling are implemented.
Existing API endpoints still use memory; they do not yet persist collections or
read database records. No AI, approval, or WordPress functionality is added.

See [PostgreSQL setup, schema, migrations, tests, backup and recovery](docs/postgresql.md)
for Ubuntu development and the dedicated self-hosted deployment design.
Render/Vercel configuration and the existing backend Dockerfile are unchanged.

## Sprint 14A: live data, explicit demo mode, and regression checks

Live mode is the default. Set `VITE_API_URL` (or the legacy
`VITE_API_BASE_URL`) to the backend URL. Missing configuration, failed HTTP
requests, and invalid JSON are displayed as errors; they never activate demo
data. Live collection starts without seeded articles or a fabricated sync time.

To run the existing sample experience explicitly, set `VITE_DEMO_MODE=true` in
`frontend/.env` and restart Vite. For a static demo build, supply that variable
at build time. Demo mode is visibly labelled and uses sample news without
calling the news backend. These are Vite build-time settings; container runtime
environment changes do not rewrite an existing frontend build.

Collection displays actual response counts and source outcomes. Processing
reports articles grouped into stories, rather than claiming exact duplicate
removal. Review and portal previews do not record approval or create WordPress
drafts. Persistence, real AI generation, approval operations, and WordPress draft
integration remain future work.

`GET /api/collect` keeps its existing fields, query validation, and HTTP status
behavior. It additionally returns `source_results`, with `name`, `url`,
`status` (`success` or `failed`), `articles_total`, and nullable `error` for each
source. Failed sources are isolated, including connector construction failures.
An all-source failure reports zero articles for that attempt and retains the
previous in-memory story list. A successful empty collection replaces that list.
The frontend also accepts older responses without `source_results`, displaying
per-source outcomes as unavailable.

Timezone-less source timestamps are interpreted as UTC, consistently with
WordPress `date_gmt`; explicit offsets are converted to UTC for comparison.
Missing, invalid, and out-of-range dates sort last. Original timestamp strings
remain unchanged in API responses. A singleton story has a similarity score of
zero (no observed match); merged stories expose the strongest actual score
against their primary article. The UI labels singletons as having no match yet.

Run backend regressions from `backend/`, using the Python environment containing
`requirements.txt`:

```bash
python -B -m unittest discover -s tests -v
```

Run frontend checks from `frontend/` after `npm ci`:

```bash
npm test
npm run typecheck
npm run build
```

Backend tests mock source connectors and exercise the in-process FastAPI API.
Frontend tests use Vitest, jsdom, and React Testing Library with mocked backend
requests. They do not access live sources, a database, AI services, or WordPress.
No deployment is part of these commands.

## Structure

- `backend/` FastAPI + SQLAlchemy + Alembic
- `frontend/` React + Vite + TypeScript + TailwindCSS

## Backend CORS for Vercel Preview

`BACKEND_CORS_ORIGINS` is a comma-separated list of exact browser origins.
Its default includes `http://localhost:5173`, `http://localhost:3000`, and
`https://hype-news-hub.vercel.app`. An environment override replaces that list,
so retain those entries when adding another exact origin. Wildcard origins
(`*`) are rejected.

`BACKEND_CORS_ORIGIN_REGEX` additionally allows this project's Vercel branch
Preview URLs and nine-character commit Preview URLs in the specified team:

```text
^https://hype-news-hub-(?:git-[a-z0-9-]+|[a-z0-9]{9})-miodrag-straks-projects\.vercel\.app$
```

This pattern is the backend default and is also shown in `backend/.env.example`.
It matches the reported Sprint 14A Preview origin. It requires HTTPS, the exact
project prefix, and the exact team suffix; unrelated projects, other teams,
lookalike domain suffixes, and `null` origins are not allowed. Matching is against
the entire origin. An empty regex environment value disables Preview matching
without disabling the exact origin list. Invalid regex syntax fails startup.

For the Render backend, the intended environment values are:

```text
BACKEND_CORS_ORIGINS=http://localhost:5173,http://localhost:3000,https://hype-news-hub.vercel.app
BACKEND_CORS_ORIGIN_REGEX=^https://hype-news-hub-(?:git-[a-z0-9-]+|[a-z0-9]{9})-miodrag-straks-projects\.vercel\.app$
```

Use literal single backslashes in the Render environment value, without shell
quotes. The backend must run the updated code for the regex setting to take
effect. Changing a frontend `VITE_*` variable cannot change backend CORS.
The live frontend API URL remains `https://hype-news-hub.onrender.com`.

Allowed requests receive their exact origin in `Access-Control-Allow-Origin`
and `Vary: Origin`. Disallowed preflights return 400 with no allow-origin header;
ordinary requests from disallowed origins have no allow-origin header, leaving
the browser to block access to the response. CORS does not authenticate requests.
Credentials, supported HTTP methods/headers, API routes, and response bodies are
unchanged. The regression suite tests actual GET and OPTIONS middleware behavior
without contacting live sources.

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Docker local startup

```bash
cp .env.example .env
# Generate the two private passwords as described in docs/postgresql.md.
docker compose up -d --wait postgres
docker compose --profile tools run --rm --build migrate
docker compose up --build
docker compose down
```

The dedicated PostgreSQL service has no published port. Its named volume is
preserved by `docker compose down`; do not add `--volumes` when retaining data.

Frontend:
http://localhost:3000

Backend:
http://localhost:8000

Swagger:
http://localhost:8000/docs

## Sprint 2: WordPress Connector

Test the first reusable WordPress connector endpoint:

```bash
GET /api/test-wordpress?url=https://hypetv.rs
```

Example response:

```json
{
	"status": "ok",
	"posts_found": 10,
	"connector": "wordpress"
}
```

Fetch normalized WordPress articles (internal format):

```bash
GET /api/fetch-wordpress?url=https://hypetv.rs&limit=5
```

Simple validation endpoint for connector QA (same normalized output):

```bash
GET /api/test-wordpress-normalized?url=https://hypetv.rs&limit=5
```

Example article item:

```json
{
	"id": "...",
	"source": "Hype Serbia",
	"source_url": "https://hypetv.rs",
	"title": "...",
	"url": "...",
	"published_at": "...",
	"excerpt": "...",
	"content": null,
	"featured_image": "...",
	"categories": [],
	"language": null
}
```

Validation targets for all Hype portals:

```bash
GET /api/test-wordpress-normalized?url=https://hypetv.hr&limit=5
GET /api/test-wordpress-normalized?url=https://hypebih.ba&limit=5
GET /api/test-wordpress-normalized?url=https://hypetv.si&limit=5
GET /api/test-wordpress-normalized?url=https://hypetv.rs&limit=5
GET /api/test-wordpress-normalized?url=https://www.hypeproduction.rs&limit=5
GET /api/test-wordpress-normalized?url=https://hypetv.mk&limit=5
```
