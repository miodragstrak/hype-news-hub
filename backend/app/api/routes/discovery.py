from fastapi import APIRouter

from app.schemas.discovery import DiscoveryResult
from app.services.source_discovery_service import discover_sources

router = APIRouter(prefix="/api", tags=["discovery"])


@router.get("/discovery", response_model=list[DiscoveryResult])
async def source_discovery() -> list[DiscoveryResult]:
    """Inspect configured sources and detect the best collection connector."""
    return await discover_sources()
