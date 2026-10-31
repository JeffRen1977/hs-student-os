from __future__ import annotations

from fastapi import APIRouter

from app.config import APP_VERSION
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse, response_model_by_alias=True)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION)
