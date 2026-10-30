from typing import Annotated
from fastapi import APIRouter, Depends
from app.api.storage import get_news_repository
from app.repositories.news_repository import PostgresNewsRepository

from app.schemas.story import StoriesResponse
from app.services.story_service import get_stories_response

router = APIRouter(prefix="/api", tags=["stories"])


@router.get("/stories", response_model=StoriesResponse)
def list_stories(repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)]) -> StoriesResponse:
    return get_stories_response(repository)
