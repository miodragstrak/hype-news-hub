from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.editorial_security import EditorialAccess, require_editorial_permission
from app.api.storage import get_news_repository
from app.core.editorial_security import EditorialPermission
from app.repositories.news_repository import PostgresNewsRepository
from app.schemas.editorial import EditorialQueueResponse
from app.schemas.editorial_queue import PrivateEditorialQueueResponse
from app.services.editorial_intelligence import get_editorial_queue_response
from app.services.editorial_queue import get_private_editorial_queue

router = APIRouter(prefix="/api", tags=["editorial"])


@router.get("/editorial-queue", response_model=EditorialQueueResponse)
def get_editorial_queue(repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)]) -> EditorialQueueResponse:
    return get_editorial_queue_response(repository)


@router.get("/editorial/queue", response_model=PrivateEditorialQueueResponse, responses={
    401: {"description": "Verified editorial identity required."},
    403: {"description": "Editorial read permission required."},
    503: {"description": "Verified identity or restricted PostgreSQL storage unavailable."},
})
def get_private_queue(
    access: Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.READ))],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> PrivateEditorialQueueResponse:
    """Newest persisted stories first (publication DESC NULLS LAST, UUID DESC).

    AI recovery_required means an expired processing reservation, not permission
    to recover. This read neither interrupts processing nor dispatches generation.
    """
    return get_private_editorial_queue(access.repository, limit, offset)
