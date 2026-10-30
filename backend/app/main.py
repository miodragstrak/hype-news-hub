from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, settings


def create_app(app_settings: Settings | None = None) -> FastAPI:
    config = app_settings if app_settings is not None else settings
    application = FastAPI(title=config.app_name)
    allowed_origins = [origin.strip() for origin in config.backend_cors_origins.split(",") if origin.strip()]

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=config.backend_cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router)
    return application


app = create_app()
