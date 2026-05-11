"""inkfish.api.routers.snapshot — GET /snapshot endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from inkfish.api.deps import get_snapshot_manager
from inkfish.api.schemas import SnapshotItem, SnapshotListResponse
from inkfish.storage.snapshot import SnapshotManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["snapshot"])


@router.get("", response_model=SnapshotListResponse, summary="List all snapshots")
@router.get("/", response_model=SnapshotListResponse, include_in_schema=False)
def list_snapshots(
    snapshots: SnapshotManager = Depends(get_snapshot_manager),  # noqa: B008
) -> SnapshotListResponse:
    """Return metadata for all persisted snapshots, ordered by tick_id ascending."""
    infos = snapshots.list_snapshots()
    logger.debug("GET /snapshot: %d snapshots found", len(infos))
    items = [
        SnapshotItem(
            tick_id=info.tick_id,
            timestamp=info.timestamp,
            parent_tick_id=info.parent_tick_id,
            char_count=info.char_count,
            action_count=info.action_count,
        )
        for info in infos
    ]
    return SnapshotListResponse(snapshots=items)
