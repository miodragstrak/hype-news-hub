"""Private queue projections; never include AI evidence, output or command data."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.ai_processing import ProcessingStatus
from app.schemas.editorial import EditorialQueueStory


class QueueAIStatus(BaseModel):
    has_suggestion: bool = False
    latest_suggestion_id: UUID | None = None
    status: ProcessingStatus | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    recovery_required: bool = False


class QueueEditorialStatus(BaseModel):
    draft_id: UUID
    status: Literal["editing", "in_review", "changes_requested", "approved", "rejected"]
    revision: int
    current_version_number: int | None


class PrivateEditorialQueueStory(EditorialQueueStory):
    # Inherited status is the collection projection, never a review/approval state.
    editorial: QueueEditorialStatus | None = None
    ai: QueueAIStatus = Field(default_factory=QueueAIStatus)


class PrivateEditorialQueueResponse(BaseModel):
    stories: list[PrivateEditorialQueueStory]
    stories_total: int = Field(ge=0)
    limit: int = Field(ge=1, le=50)
    offset: int = Field(ge=0, le=1_000_000)
    has_more: bool
