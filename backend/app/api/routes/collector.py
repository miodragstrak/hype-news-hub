from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from app.api.storage import get_news_repository
from app.repositories.news_repository import PostgresNewsRepository

from app.schemas.collector import CollectArticlesResponse
from app.services.collector import collect_articles

router = APIRouter(prefix="/api", tags=["collector"])


@router.get("/collect", response_model=CollectArticlesResponse)
async def collect_articles_endpoint(
    response: Response,
    repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)],
    limit_per_source: int = Query(5, ge=1, le=50, description="Number of latest posts to fetch from each source"),
) -> CollectArticlesResponse:
    headers = {}
    result = await collect_articles(limit_per_source=limit_per_source, repository=repository, response_headers=headers)
    response.headers.update(headers)
    return result
