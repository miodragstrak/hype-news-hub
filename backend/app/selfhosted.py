"""Sprint 14A composition: infrastructure can be checked, application access stays closed."""
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse

from app.selfhosted_config import load_database_secrets


def create_selfhosted_app(config=None):
    if config is None:
        load_database_secrets()
        # Import after loading file secrets; normal Render composition never calls this loader.
        from app.core.config import Settings
        config = Settings(_env_file=None)
    try:
        origin = urlsplit(config.backend_cors_origins)
        valid_origin = (origin.scheme == "https" and bool(origin.hostname) and origin.username is None
                        and origin.password is None and not origin.path and not origin.query and not origin.fragment
                        and not any(c.isspace() or c == "," for c in config.backend_cors_origins)
                        and (origin.port is None or 1 <= origin.port <= 65535))
    except ValueError:
        valid_origin = False
    if (config.app_env != "production" or config.news_storage_backend != "postgres"
            or not config.postgres_password.get_secret_value() or config.ai_processing_provider != "disabled"
            or config.backend_cors_origin_regex is not None or not valid_origin):
        raise ValueError("Self-hosted infrastructure requires production PostgreSQL, one HTTPS origin and disabled AI.")
    from app.main import create_app
    from app.api.readiness import router
    application = create_app(config)
    application.include_router(router)

    @application.middleware("http")
    async def activation_gate(request, call_next):
        # No environment switch removes this gate. Sprint 14B must compose a real
        # identity verifier and verified ingress before enabling application routes.
        if request.url.path not in {"/", "/ready"}:
            return JSONResponse({"detail": "Self-hosted editorial access is not activated."}, status_code=503,
                                headers={"Cache-Control": "no-store"})
        return await call_next(request)

    return application
