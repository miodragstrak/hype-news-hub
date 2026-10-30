from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool

from app.api.router import api_router
from app.core.config import Settings, settings
from app.repositories.news_repository import CollectionBusy, PostgresNewsRepository, STORAGE_HEADERS, StorageUnavailable


def create_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings if app_settings is not None else settings

    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            repository = application.state.news_repository
            if repository is not None and "engine" in repository.__dict__:
                await run_in_threadpool(repository.engine.dispose)

    application = FastAPI(title=config.app_name, lifespan=lifespan)
    application.state.news_repository = PostgresNewsRepository(config) if config.news_storage_backend == "postgres" else None
    allowed_origins = [origin.strip() for origin in config.backend_cors_origins.split(",") if origin.strip()]

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=config.backend_cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=STORAGE_HEADERS,
    )

    application.include_router(api_router)

    @application.exception_handler(StorageUnavailable)
    async def storage_unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": "PostgreSQL storage is unavailable or misconfigured. No memory fallback was used."},
                            headers={"X-News-Storage": "postgres", "X-Collection-State": "unavailable"})

    @application.exception_handler(CollectionBusy)
    async def collection_busy(request, exc):
        return JSONResponse(status_code=409, content={"detail": "Another collection is already running. Retry after it finishes."},
                            headers={"Retry-After": "10", "X-News-Storage": "postgres", "X-Collection-State": "running"})
    return application


app = create_app()
