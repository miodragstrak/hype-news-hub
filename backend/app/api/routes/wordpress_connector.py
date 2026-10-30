from fastapi import APIRouter, HTTPException, Query

from app.config.sources import configured_diagnostic_source
from app.connectors.errors import SourceFetchError, SourceSecurityError
from app.schemas.article import NormalizedArticle
from app.services.source_collection import normalize_source_batch

router = APIRouter(prefix="/api", tags=["connectors"])


def _source(url):
    try:
        return configured_diagnostic_source(url)
    except SourceSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None


async def _fetch_normalized(source, limit):
    try:
        connector = source.connector_factory(source.url)
        posts = await connector.fetch_latest(limit=limit)
        return normalize_source_batch(posts, source.url, source.connector, source.name)
    except SourceSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except SourceFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/test-wordpress")
async def test_wordpress_connector(url: str = Query(..., description="WordPress site base URL")) -> dict[str, object]:
    source = _source(url)
    connector = source.connector_factory(source.url)
    connection = await connector.test_connection()

    if not connection.get("success"):
        if str(connection.get("error", "")).startswith("unsafe_destination:"):
            raise HTTPException(status_code=403, detail=str(SourceSecurityError()))
        return {
            "status": "error",
            "posts_found": 0,
            "connector": "wordpress",
            "error": connection.get("error"),
        }

    try:
        posts = await connector.fetch_latest(limit=10)
        normalized = normalize_source_batch(posts, source.url, source.connector, source.name)
    except SourceSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except SourceFetchError as exc:
        return {
            "status": "error",
            "posts_found": 0,
            "connector": "wordpress",
            "error": str(exc),
        }

    return {
        "status": "ok",
        "posts_found": len(normalized),
        "connector": "wordpress",
    }


@router.get("/fetch-wordpress", response_model=list[NormalizedArticle])
async def fetch_wordpress_articles(
    url: str = Query(..., description="WordPress site base URL"),
    limit: int = Query(10, ge=1, le=50, description="Number of latest posts to fetch"),
) -> list[NormalizedArticle]:
    return await _fetch_normalized(_source(url), limit)


@router.get("/test-wordpress-normalized", response_model=list[NormalizedArticle])
async def test_wordpress_normalized(
    url: str = Query(..., description="WordPress site base URL"),
    limit: int = Query(10, ge=1, le=50, description="Number of latest posts to fetch"),
) -> list[NormalizedArticle]:
    """Simple testing endpoint for validating normalized WordPress output."""
    return await _fetch_normalized(_source(url), limit)
