from fastapi import APIRouter

from app.schemas.editorial import EditorialQueueResponse
from app.services.editorial_intelligence import get_editorial_queue_response

router = APIRouter(prefix="/api", tags=["editorial"])


@router.get("/editorial-queue", response_model=EditorialQueueResponse)
async def get_editorial_queue() -> EditorialQueueResponse:
    return get_editorial_queue_response()
