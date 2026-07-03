from fastapi import APIRouter

from app.schemas.story import StoriesResponse
from app.services.story_service import get_stories_response

router = APIRouter(prefix="/api", tags=["stories"])


@router.get("/stories", response_model=StoriesResponse)
async def list_stories() -> StoriesResponse:
    return get_stories_response()
