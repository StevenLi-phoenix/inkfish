"""inkfish.api.routers.simulation — POST /simulation/{start,pause,reset} endpoints.

P0 note: /start runs the simulation synchronously (BLOCKING) before returning.
This is intentional for P0's single-threaded synchronous design.
Real async/background-task wiring is deferred to P6.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from inkfish.api.deps import (
    get_repository,
    get_settings,
    get_sim_config,
    get_snapshot_manager,
)
from inkfish.api.schemas import (
    PauseRequest,
    ResetRequest,
    ResetResponse,
    StartSimulationRequest,
    StartSimulationResponse,
)
from inkfish.config import Settings, SimConfig
from inkfish.llm.deepseek import DeepSeekClient
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
from inkfish.tick.scheduler import run_simulation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulation"])


@router.post(
    "/start",
    response_model=StartSimulationResponse,
    status_code=202,
    summary="Start simulation (P0: BLOCKING synchronous call)",
)
async def start(
    req: StartSimulationRequest,
    repo: Repository = Depends(get_repository),  # noqa: B008
    snapshots: SnapshotManager = Depends(get_snapshot_manager),  # noqa: B008
    sim_cfg: SimConfig = Depends(get_sim_config),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> StartSimulationResponse:
    """Run *n_ticks* of simulation starting from *from_tick* (or the latest tick).

    **P0 behaviour**: this call blocks until all ticks complete.
    The ``task_id`` in the response is informational (no async tracking in P0).

    Raises:
        400: No characters found at the requested start tick (seed first).
    """
    start_tick = req.from_tick if req.from_tick is not None else (repo.get_latest_tick_id() or 0)

    # Validate characters exist at start_tick
    try:
        world = snapshots.load_world(start_tick)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No snapshot found at tick={start_tick}. Seed the simulation first.",
        ) from exc

    if not world.characters:
        raise HTTPException(
            status_code=400,
            detail="No characters at start_tick; seed the simulation first.",
        )

    client = DeepSeekClient(settings.deepseek_api_key, model=sim_cfg.model)

    logger.info(
        "POST /simulation/start: n_ticks=%d from_tick=%d chars=%d",
        req.n_ticks,
        start_tick,
        len(world.characters),
    )

    await run_simulation(
        req.n_ticks,
        world=world,
        client=client,
        repo=repo,
        snapshots=snapshots,
        start_tick=start_tick,
        sim_config=sim_cfg,
    )

    return StartSimulationResponse(
        task_id=str(uuid.uuid4()),
        started_at=datetime.now(UTC),
        n_ticks=req.n_ticks,
        from_tick=start_tick,
    )


@router.post("/pause", summary="Pause simulation (P0: no-op)")
def pause(req: PauseRequest) -> dict:  # type: ignore[type-arg]
    """Signal simulation to pause at the next tick boundary.

    **P0 behaviour**: no-op — synchronous mode has no running task to pause.
    """
    logger.debug("POST /simulation/pause: reason=%r (no-op in P0)", req.reason)
    return {
        "status": "noop",
        "phase": "P0",
        "reason": req.reason,
        "note": "Sync mode in P0; no running task to pause.",
    }


@router.post("/reset", response_model=ResetResponse, summary="Reset simulation timeline")
def reset(
    req: ResetRequest,
    snapshots: SnapshotManager = Depends(get_snapshot_manager),  # noqa: B008
) -> ResetResponse:
    """Delete all simulation data after *tick_id*.

    Pass ``tick_id=-1`` to wipe all simulation data (llm_logs are preserved).
    """
    logger.info("POST /simulation/reset: tick_id=%d", req.tick_id)
    snapshots.reset(req.tick_id)
    return ResetResponse(reset_to_tick=req.tick_id, rows_deleted=-1)
