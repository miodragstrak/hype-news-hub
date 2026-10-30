from typing import Annotated
from fastapi import APIRouter, Depends
from app.api.storage import get_news_repository
from app.repositories.news_repository import PostgresNewsRepository

from app.schemas.editorial import EditorialQueueResponse
from app.services.editorial_intelligence import get_editorial_queue_response

router = APIRouter(prefix="/api", tags=["editorial"])


@router.get("/editorial-queue", response_model=EditorialQueueResponse)
def get_editorial_queue(repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)]) -> EditorialQueueResponse:
    return get_editorial_queue_response(repository)
