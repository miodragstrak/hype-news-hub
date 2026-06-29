from fastapi import APIRouter, HTTPException, Query

from app.connectors.wordpress import WordPressConnector
from app.schemas.article import NormalizedArticle
from app.services.article_normalizer import normalize_articles

router = APIRouter(prefix="/api", tags=["connectors"])


@router.get("/test-wordpress")
async def test_wordpress_connector(url: str = Query(..., description="WordPress site base URL")) -> dict[str, object]:
    connector = WordPressConnector(base_url=url)
    connection = await connector.test_connection()

    if not connection.get("success"):
        return {
            "status": "error",
            "posts_found": 0,
            "connector": "wordpress",
            "error": connection.get("error"),
        }

    try:
        posts = await connector.fetch_latest(limit=10)
    except Exception as exc:
        return {
            "status": "error",
            "posts_found": 0,
            "connector": "wordpress",
            "error": str(exc),
        }

    return {
        "status": "ok",
        "posts_found": len(posts),
        "connector": "wordpress",
    }


@router.get("/fetch-wordpress", response_model=list[NormalizedArticle])
async def fetch_wordpress_articles(
    url: str = Query(..., description="WordPress site base URL"),
    limit: int = Query(10, ge=1, le=50, description="Number of latest posts to fetch"),
) -> list[NormalizedArticle]:
    connector = WordPressConnector(base_url=url)
    connection = await connector.test_connection()

    if not connection.get("success"):
        error_message = str(connection.get("error") or "Unable to connect to WordPress source")
        if error_message == "Invalid URL":
            raise HTTPException(status_code=400, detail=error_message)
        raise HTTPException(status_code=502, detail=error_message)

    try:
        connector_articles = await connector.fetch_latest(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return normalize_articles(connector_articles=connector_articles, source_url=url)


@router.get("/test-wordpress-normalized", response_model=list[NormalizedArticle])
async def test_wordpress_normalized(
    url: str = Query(..., description="WordPress site base URL"),
    limit: int = Query(10, ge=1, le=50, description="Number of latest posts to fetch"),
) -> list[NormalizedArticle]:
    """Simple testing endpoint for validating normalized WordPress output."""
    connector = WordPressConnector(base_url=url)
    connection = await connector.test_connection()

    if not connection.get("success"):
        error_message = str(connection.get("error") or "Unable to connect to WordPress source")
        if error_message == "Invalid URL":
            raise HTTPException(status_code=400, detail=error_message)
        raise HTTPException(status_code=502, detail=error_message)

    try:
        connector_articles = await connector.fetch_latest(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return normalize_articles(connector_articles=connector_articles, source_url=url)
