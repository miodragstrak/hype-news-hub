"""Infrastructure-only readiness; never probes an AI provider or performs writes."""
import logging
from pathlib import Path

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app import models  # Register all managed tables.
from app.database.base import Base
from app.database.runtime_security import assert_runtime_role
from app.selfhosted_config import assert_migration_marker_permissions

logger = logging.getLogger(__name__)
router = APIRouter()


def check_database(repository) -> None:
    from app.models.auth import AuthBase
    from app.services.authentication import AUTH_POLICY
    expected = ScriptDirectory(str(Path(__file__).resolve().parents[2] / "alembic")).get_current_head()
    tables = list(Base.metadata.sorted_tables) + list(AuthBase.metadata.sorted_tables)
    if not expected or {table.name for table in tables} != set(AUTH_POLICY):
        raise ValueError("Required schema definition is unavailable.")
    with repository.engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '3s'")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
        assert_runtime_role(connection, policy=AUTH_POLICY)
        # Self-hosted provisioning adds only SELECT(version_num), never migration rights.
        if connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() != [expected]:
            raise ValueError("Required schema revision is unavailable.")
        assert_migration_marker_permissions(connection)
        for table in tables:
            connection.execute(select(table).limit(0))
            for privilege in AUTH_POLICY[table.name]:
                if not connection.execute(text("SELECT pg_catalog.has_table_privilege(current_user, :table, :privilege)"),
                                          {"table": "public." + table.name, "privilege": privilege}).scalar_one():
                    raise ValueError("Required runtime grants are unavailable.")
        if repository.config.auth_enabled:
            if not connection.execute(text("SELECT EXISTS(SELECT 1 FROM public.app_users WHERE active AND role='admin')")).scalar_one():
                raise ValueError("Initial administrator is required.")


@router.get("/ready", include_in_schema=False)
def readiness(request: Request):
    try:
        check_database(request.app.state.news_repository)
    except Exception as exc:
        logger.warning("Infrastructure readiness failed (%s)", type(exc).__name__)
        return JSONResponse({"status": "not_ready", "scope": "infrastructure"}, status_code=503,
                            headers={"Cache-Control": "no-store"})
    enabled = request.app.state.news_repository.config.auth_enabled
    return JSONResponse({"status": "ready", "scope": "infrastructure", "editorial_access": "authenticated" if enabled else "blocked"},
                        headers={"Cache-Control": "no-store"})
