"""Private AI suggestions and explicit acceptance; no approval or publishing."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.editorial_security import EditorialAccess, require_editorial_permission
from app.core.editorial_security import EditorialPermission
from app.schemas.ai_processing import AcceptSuggestion, CreateSuggestion, RejectSuggestion, SuggestionRead, SuggestionSummary
from app.schemas.editorial_commands import CommandResult, EditorialAPIError
from app.services.ai_processing import AIProcessing
from app.services.editorial_commands import EditorialCommandError

router = APIRouter(prefix="/api/editorial/ai/suggestions", tags=["ai-suggestions"], responses={
    400: {"model": EditorialAPIError, "description": "Malformed UTF-8 JSON or non-finite numbers."},
    401: {"description": "Verified editorial identity required."},
    403: {"description": "Insufficient editorial permission."},
    404: {"description": "Persisted story or suggestion not found."},
    409: {"description": "Command conflict, stale revision or invalid rejection."},
    413: {"description": "Command exceeds the 1 MiB request limit."},
    415: {"description": "Commands require UTF-8 JSON."},
    422: {"model": EditorialAPIError, "description": "Invalid source/parameters or size budget exceeded."},
    429: {"description": "Daily backend generation budget exhausted; no provider dispatch."},
    503: {"description": "Identity, restricted PostgreSQL, migration or provider unavailable."},
})
Reader = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.READ))]
Editor = Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.EDIT))]


def service(access, request):
    return AIProcessing(access.repository, access.principal, request.app.state.ai_provider)


def api_error(exc):
    return HTTPException(exc.status, exc.detail, headers={"Cache-Control": "no-store"})


@router.post("", response_model=SuggestionRead, status_code=201, responses={
    200: {"model": SuggestionRead, "description": "Existing completed/failed/recovered command; never regenerated."},
    202: {"model": SuggestionRead, "description": "The original command is still processing."},
})
async def create_suggestion(command: CreateSuggestion, access: Editor, request: Request, response: Response):
    """Generate a source-grounded suggestion using the explicitly configured provider. Failed processing is explicit in status/error_code.

    Retry the identical command_id and payload to recover its durable record. A new
    command_id is an explicit new attempt, with newly captured evidence. No automatic retry.
    """
    try:
        result, created = await service(access, request).generate(command)
    except EditorialCommandError as exc:
        raise api_error(exc) from None
    response.status_code = 202 if result.status == "processing" else 201 if created else 200
    return result


@router.get("", response_model=list[SuggestionSummary])
def list_suggestions(story_id: UUID, access: Reader, request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 20, offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
    """Lightweight summaries, excluding input evidence, output bodies and events."""
    try:
        return service(access, request).list(story_id, limit, offset)
    except EditorialCommandError as exc:
        raise api_error(exc) from None


@router.get("/{suggestion_id}", response_model=SuggestionRead)
def read_suggestion(suggestion_id: UUID, access: Reader, request: Request):
    """Read exact frozen input and sealed output. Expired records advertise recovery_required."""
    try:
        return service(access, request).get(suggestion_id)
    except EditorialCommandError as exc:
        raise api_error(exc) from None


@router.post("/{suggestion_id}/reject", response_model=SuggestionRead)
def reject_suggestion(suggestion_id: UUID, command: RejectSuggestion, access: Editor, request: Request):
    """Reject only a successful suggestion, preserving its immutable evidence and output."""
    try:
        return service(access, request).reject(suggestion_id, command)
    except EditorialCommandError as exc:
        raise api_error(exc) from None


@router.post("/{suggestion_id}/accept", response_model=CommandResult)
def accept_suggestion(suggestion_id: UUID, command: AcceptSuggestion, access: Editor, request: Request):
    """Explicit human acceptance, atomically saved as an AI-origin editing version.

    expected_revision=0 creates a workspace; otherwise supply its current revision.
    Retry the identical command ID/payload to recover the original version receipt.
    """
    try:
        return service(access, request).accept(suggestion_id, command)
    except EditorialCommandError as exc:
        raise api_error(exc) from None
