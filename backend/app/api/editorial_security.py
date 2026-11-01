"""Reusable fail-closed FastAPI boundary for all future private editorial routes."""
from dataclasses import dataclass
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.core.editorial_security import (
    EditorialIdentityUnavailable, EditorialPermission, EditorialPrincipal, InvalidEditorialIdentity,
)
from app.repositories.news_repository import PostgresNewsRepository

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False, scheme_name="EditorialBearer")
_EDITORIAL_TABLES = (
    "editorial_drafts", "editorial_draft_versions", "editorial_version_sources",
    "editorial_decisions", "editorial_events",
)


async def get_editorial_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> EditorialPrincipal:
    if credentials is None:
        raise HTTPException(401, "Editorial authentication is required.", headers={"WWW-Authenticate": "Bearer"})
    try:
        principal = await request.app.state.editorial_identity_verifier.verify(credentials.credentials)
        if not isinstance(principal, EditorialPrincipal):
            raise EditorialIdentityUnavailable()
        return principal
    except InvalidEditorialIdentity:
        raise HTTPException(401, "Editorial credentials are invalid.", headers={"WWW-Authenticate": "Bearer"}) from None
    except Exception as exc:
        # Do not log tokens, provider error text, claims, or connection details.
        logger.warning("Editorial identity verification unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Editorial identity verification is unavailable.") from None


def get_editorial_database(request: Request) -> PostgresNewsRepository:
    repository = request.app.state.news_repository
    if repository is None:
        raise HTTPException(503, "Private editorial operations require PostgreSQL.")
    # A read-only transaction also rejects owner credentials. Missing migrations,
    # credentials, grants or connectivity fail through the existing safe 503 handler.
    with repository.read() as session:
        for table in _EDITORIAL_TABLES:
            session.execute(text(f"SELECT 1 FROM public.{table} LIMIT 0"))
    return repository


@dataclass(frozen=True)
class EditorialAccess:
    principal: EditorialPrincipal
    repository: PostgresNewsRepository


def require_editorial_permission(permission: EditorialPermission):
    def authorize(
        request: Request,
        response: Response,
        principal: Annotated[EditorialPrincipal, Depends(get_editorial_principal)],
    ) -> EditorialAccess:
        if permission not in principal.permissions:
            raise HTTPException(403, "Insufficient editorial permission.")
        # Authorize before probing the database; unauthorized callers cannot use
        # this dependency to inspect database availability or configuration.
        access = EditorialAccess(principal, get_editorial_database(request))
        response.headers["Cache-Control"] = "no-store"
        return access

    return authorize
