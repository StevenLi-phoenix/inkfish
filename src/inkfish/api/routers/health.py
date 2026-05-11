"""inkfish.api.routers.health — GET /health endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from inkfish.api.deps import get_repository
from inkfish.api.schemas import HealthResponse
from inkfish.storage.repository import Repository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("", response_model=HealthResponse)
@router.get("/", response_model=HealthResponse, include_in_schema=False)
def health(repo: Repository = Depends(get_repository)) -> HealthResponse:  # noqa: B008
    """Return the current health and simulation status.

    ``sim_running`` is always False in P0 (synchronous execution; no background task).
    """
    latest = repo.get_latest_tick_id()
    logger.debug("Health check: latest_tick=%s", latest)
    return HealthResponse(
        status="ok",
        phase="P0",
        latest_tick=latest,
        sim_running=False,
    )
