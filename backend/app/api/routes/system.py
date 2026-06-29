from fastapi import APIRouter

from app.core.config import settings
from app.schemas.system import SystemStatusResponse

router = APIRouter()


@router.get("/", response_model=SystemStatusResponse)
def read_root() -> SystemStatusResponse:
    return SystemStatusResponse(name=settings.app_name, status="running")
