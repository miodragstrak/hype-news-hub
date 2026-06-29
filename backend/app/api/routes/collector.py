from fastapi import APIRouter, Query

from app.schemas.collector import CollectArticlesResponse
from app.services.collector import collect_articles

router = APIRouter(prefix="/api", tags=["collector"])


@router.get("/collect", response_model=CollectArticlesResponse)
async def collect_articles_endpoint(
    limit_per_source: int = Query(5, ge=1, le=50, description="Number of latest posts to fetch from each source"),
) -> CollectArticlesResponse:
    return await collect_articles(limit_per_source=limit_per_source)
