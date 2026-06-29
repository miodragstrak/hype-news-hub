from fastapi import APIRouter

from app.api.routes.collector import router as collector_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.system import router as system_router
from app.api.routes.wordpress_connector import router as wordpress_connector_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(collector_router)
api_router.include_router(discovery_router)
api_router.include_router(wordpress_connector_router)
