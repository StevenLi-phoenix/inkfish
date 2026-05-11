"""inkfish.api.routers.tick — GET /tick and GET /tick/{tick_id} endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from inkfish.api.deps import get_repository, get_snapshot_manager
from inkfish.api.schemas import TickActionItem, TickResponse
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tick"])


def _build_tick_response(
    tick_id: int,
    repo: Repository,
    snapshots: SnapshotManager,
) -> TickResponse:
    """Construct a TickResponse from repository data for *tick_id*.

    Raises:
        HTTPException 404: if no snapshot exists for *tick_id*.
    """
    snap = repo.get_snapshot_meta(tick_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Tick {tick_id} not found.")

    action_rows = repo.get_actions_at_tick(tick_id)
    actions = [
        TickActionItem(
            id=row.id,
            character_id=row.character_id,
            action_type=row.action_type,
            content=row.content,
            target=row.target,
            mood=row.mood,
            inner_thought=row.inner_thought,
            triggers_interaction=row.triggers_interaction,
            created_at=row.created_at,
        )
        for row in action_rows
    ]

    return TickResponse(
        tick_id=snap.tick_id,
        timestamp=snap.timestamp,
        parent_tick_id=snap.parent_tick_id,
        char_count=snap.char_count,
        action_count=snap.action_count,
        actions=actions,
    )


@router.get("", response_model=TickResponse, summary="Get latest tick state")
@router.get("/", response_model=TickResponse, include_in_schema=False)
def get_latest_tick(
    repo: Repository = Depends(get_repository),  # noqa: B008
    snapshots: SnapshotManager = Depends(get_snapshot_manager),  # noqa: B008
) -> TickResponse:
    """Return the most recent tick's state and all its actions.

    Raises:
        404: If no ticks have been simulated yet.
    """
    latest = repo.get_latest_tick_id()
    if latest is None:
        raise HTTPException(status_code=404, detail="No ticks found. Seed and run first.")
    logger.debug("GET /tick: latest_tick=%d", latest)
    return _build_tick_response(latest, repo, snapshots)


@router.get("/{tick_id}", response_model=TickResponse, summary="Get specific tick state")
def get_tick_by_id(
    tick_id: int,
    repo: Repository = Depends(get_repository),  # noqa: B008
    snapshots: SnapshotManager = Depends(get_snapshot_manager),  # noqa: B008
) -> TickResponse:
    """Return the state and actions for the specified *tick_id*.

    Raises:
        404: If the requested tick does not exist.
    """
    logger.debug("GET /tick/%d", tick_id)
    return _build_tick_response(tick_id, repo, snapshots)
