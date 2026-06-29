# Hype News Hub

Internal application for aggregating and processing entertainment news.

## Structure

- `backend/` FastAPI + SQLAlchemy + Alembic
- `frontend/` React + Vite + TypeScript + TailwindCSS

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
