from fastapi import APIRouter, HTTPException

from app.schemas.editorial import EditorialStoryWorkspace
from app.services.editorial_story_service import generate_demo_serbian_draft, get_editorial_story_workspace

router = APIRouter(prefix="/api", tags=["editorial-stories"])


@router.get("/editorial-stories/{story_id}", response_model=EditorialStoryWorkspace)
async def get_editorial_story(story_id: str) -> EditorialStoryWorkspace:
    editorial_story = get_editorial_story_workspace(story_id)
    if editorial_story is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' was not found.")

    return editorial_story


@router.post("/editorial-stories/{story_id}/generate-demo-draft", response_model=EditorialStoryWorkspace)
async def generate_editorial_story_demo_draft(story_id: str) -> EditorialStoryWorkspace:
    editorial_story = generate_demo_serbian_draft(story_id)
    if editorial_story is None:
        raise HTTPException(status_code=404, detail=f"Story '{story_id}' was not found.")

    return editorial_story
