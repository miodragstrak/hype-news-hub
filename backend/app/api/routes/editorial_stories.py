from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.api.storage import get_news_repository
from app.repositories.news_repository import PostgresNewsRepository

from app.schemas.editorial import EditorialStoryWorkspace
from app.services.editorial_story_service import generate_demo_serbian_draft, get_editorial_story_workspace

router = APIRouter(prefix="/api", tags=["editorial-stories"])


@router.get("/editorial-stories/{story_id}", response_model=EditorialStoryWorkspace)
def get_editorial_story(story_id: str, repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)]) -> EditorialStoryWorkspace:
    editorial_story = get_editorial_story_workspace(story_id, repository)
    if editorial_story is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' was not found.")

    return editorial_story


@router.post("/editorial-stories/{story_id}/generate-demo-draft", response_model=EditorialStoryWorkspace)
def generate_editorial_story_demo_draft(story_id: str, repository: Annotated[PostgresNewsRepository | None, Depends(get_news_repository)]) -> EditorialStoryWorkspace:
    editorial_story = generate_demo_serbian_draft(story_id, repository)
    if editorial_story is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' was not found.")

    return editorial_story
