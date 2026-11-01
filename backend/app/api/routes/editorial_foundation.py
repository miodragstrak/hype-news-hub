"""Authenticated capability boundary for the PostgreSQL editorial workflow."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.editorial_security import EditorialAccess, require_editorial_permission
from app.core.editorial_security import EditorialPermission, EditorialRole

router = APIRouter(prefix="/api/editorial", tags=["editorial-foundation"])


class EditorialCapabilities(BaseModel):
    roles: list[EditorialRole]
    permissions: list[EditorialPermission]
    storage: Literal["postgres"] = "postgres"
    commands_enabled: bool = False


@router.get("/capabilities", response_model=EditorialCapabilities, responses={
    401: {"description": "Missing or invalid editorial credentials."},
    403: {"description": "Verified identity lacks editorial read permission."},
    503: {"description": "Identity verification or restricted PostgreSQL editorial storage is unavailable."},
})
def get_editorial_capabilities(
    access: Annotated[EditorialAccess, Depends(require_editorial_permission(EditorialPermission.READ))],
) -> EditorialCapabilities:
    return EditorialCapabilities(roles=sorted(access.principal.roles), permissions=sorted(access.principal.permissions),
        commands_enabled=bool(access.principal.permissions & {
            EditorialPermission.EDIT, EditorialPermission.SUBMIT, EditorialPermission.REVIEW}))
