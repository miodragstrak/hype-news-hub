"""Authenticated PostgreSQL editorial API; no collection/demo response changes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.editorial_security import EditorialAccess, require_editorial_permission
from app.core.editorial_security import EditorialPermission
from app.schemas.editorial_commands import (AuditEvent, CommandResult, CreateDraft, DecisionCommand,
    DraftRead, EditorialAPIError, NegativeDecisionCommand, SaveRevision, StorySource, VersionCommand, VersionRead, VersionSummary)
from app.services.editorial_commands import EditorialCommands, EditorialCommandError

router = APIRouter(prefix="/api/editorial/drafts", tags=["editorial-workflow"], responses={
    400: {"model": EditorialAPIError, "description": "Malformed JSON, invalid UTF-8/Unicode or a non-finite number."},
    401: {"description": "Missing or invalid verified identity."},
    403: {"description": "Verified identity lacks the operation's permission."},
    404: {"description": "Persisted story or editorial draft not found."},
    409: {"description": "Stale revision, invalid transition, duplicate workspace or conflicting command ID."},
    413: {"description": "Editorial command exceeds the 1 MiB JSON request limit."},
    415: {"model": EditorialAPIError, "description": "Unsupported command content type or charset."},
    422: {"model": EditorialAPIError, "description": "Invalid editorial parameters/payload or response budget exceeded."},
    503: {"description": "Identity verification or restricted PostgreSQL storage is unavailable."},
})
Reader = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.READ))]
Editor = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.EDIT))]
Submitter = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.SUBMIT))]
Reviewer = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.REVIEW))]
story_router = APIRouter(prefix="/api/editorial/stories", tags=["editorial-workflow"], responses=router.responses)


def invoke(access, method, *args, **kwargs):
    try:
        return getattr(EditorialCommands(access.repository, access.principal), method)(*args, **kwargs)
    except EditorialCommandError as exc:
        raise HTTPException(exc.status, exc.detail, headers={"Cache-Control": "no-store"}) from None


@story_router.get("/{story_id}/sources", response_model=list[StorySource])
def story_sources(story_id: UUID, access: Reader, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
    """Obtain stable article/source UUID pairs before creating a workspace."""
    return invoke(access, "story_sources", story_id, limit, offset)


@router.post("", response_model=CommandResult, status_code=201)
def create_draft(command: CreateDraft, access: Editor):
    """Create one sr-Latn workspace. expected_revision=0; command_id is retry identity."""
    return invoke(access, "create", command)


@router.get("", response_model=DraftRead)
def find_draft(story_id: UUID, access: Reader):
    """Find the private sr-Latn workspace for a stable persisted story UUID."""
    return invoke(access, "get", story_id=story_id)


@router.get("/{draft_id}", response_model=DraftRead)
def read_draft(draft_id: UUID, access: Reader):
    """Read the current workspace, payload, frozen sources and effective approval."""
    return invoke(access, "get", draft_id)


@router.post("/{draft_id}/revisions", response_model=CommandResult)
def save_revision(draft_id: UUID, command: SaveRevision, access: Editor):
    """Save a complete replacement payload as a new immutable manual version."""
    return invoke(access, "execute", draft_id, "save", command)


@router.post("/{draft_id}/submit", response_model=CommandResult)
def submit_for_review(draft_id: UUID, command: VersionCommand, access: Submitter):
    return invoke(access, "execute", draft_id, "submit", command)


@router.post("/{draft_id}/approve", response_model=CommandResult)
def approve(draft_id: UUID, command: DecisionCommand, access: Reviewer):
    return invoke(access, "execute", draft_id, "approve", command)


@router.post("/{draft_id}/request-changes", response_model=CommandResult)
def request_changes(draft_id: UUID, command: NegativeDecisionCommand, access: Reviewer):
    return invoke(access, "execute", draft_id, "request_changes", command)


@router.post("/{draft_id}/reject", response_model=CommandResult)
def reject(draft_id: UUID, command: NegativeDecisionCommand, access: Reviewer):
    return invoke(access, "execute", draft_id, "reject", command)


@router.post("/{draft_id}/reopen", response_model=CommandResult)
def reopen(draft_id: UUID, command: NegativeDecisionCommand, access: Editor):
    return invoke(access, "execute", draft_id, "reopen", command)


@router.get("/{draft_id}/versions", response_model=list[VersionSummary])
def version_history(draft_id: UUID, access: Reader, limit: Annotated[int, Query(ge=1, le=50)] = 20,
                    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
    """List bounded metadata summaries; retrieve content with the version detail endpoint."""
    return invoke(access, "history", draft_id, "versions", limit, offset)


@router.get("/{draft_id}/versions/{version_number}", response_model=VersionRead)
def version_detail(draft_id: UUID, version_number: Annotated[int, Path(ge=1, le=2_147_483_647)], access: Reader):
    """Read exactly one immutable version with its complete payload and frozen sources."""
    return invoke(access, "get_version", draft_id, version_number)


@router.get("/{draft_id}/events", response_model=list[AuditEvent])
def audit_timeline(draft_id: UUID, access: Reader, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                   offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
    return invoke(access, "history", draft_id, "events", limit, offset)
