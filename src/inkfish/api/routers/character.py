"""inkfish.api.routers.character — GET /character and GET /character/{id} endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from inkfish.api.deps import get_repository
from inkfish.api.schemas import (
    CharacterDetailResponse,
    CharacterItem,
    CharacterListResponse,
    TickActionItem,
)
from inkfish.storage.repository import Repository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["character"])

_DEFAULT_RECENT_ACTIONS = 10


def _row_to_item(row: object) -> CharacterItem:  # type: ignore[type-arg]
    """Convert a CharacterRow ORM instance to a CharacterItem DTO."""
    return CharacterItem(
        id=row.id,  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        mbti=row.mbti,  # type: ignore[attr-defined]
        age=row.age,  # type: ignore[attr-defined]
        current_location=row.current_location,  # type: ignore[attr-defined]
        current_mood=row.current_mood,  # type: ignore[attr-defined]
        weight=row.weight,  # type: ignore[attr-defined]
        alive=row.alive,  # type: ignore[attr-defined]
        appearance_count=row.appearance_count,  # type: ignore[attr-defined]
        last_active_tick=row.last_active_tick,  # type: ignore[attr-defined]
    )


@router.get("", response_model=CharacterListResponse, summary="List characters at latest tick")
@router.get("/", response_model=CharacterListResponse, include_in_schema=False)
def list_characters(
    repo: Repository = Depends(get_repository),  # noqa: B008
) -> CharacterListResponse:
    """Return all characters snapshotted at the latest tick.

    Raises:
        404: If no ticks have been simulated yet.
    """
    latest = repo.get_latest_tick_id()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="No ticks found. Seed the simulation first.",
        )

    char_rows = repo.get_characters_at_tick(latest)
    logger.debug("GET /character: tick=%d chars=%d", latest, len(char_rows))
    return CharacterListResponse(
        tick_id=latest,
        characters=[_row_to_item(r) for r in char_rows],
    )


@router.get(
    "/{character_id}",
    response_model=CharacterDetailResponse,
    summary="Get character detail with recent actions",
)
def get_character(
    character_id: str,
    recent: int = Query(default=_DEFAULT_RECENT_ACTIONS, ge=1, le=100),  # noqa: B008
    repo: Repository = Depends(get_repository),  # noqa: B008
) -> CharacterDetailResponse:
    """Return full character details plus their most recent *recent* actions.

    Looks up the character at the latest snapshot tick.

    Raises:
        404: If no ticks exist or the character is not found.
    """
    latest = repo.get_latest_tick_id()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="No ticks found. Seed the simulation first.",
        )

    char_rows = repo.get_characters_at_tick(latest)
    char_row = next((r for r in char_rows if r.id == character_id), None)
    if char_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Character '{character_id}' not found at tick {latest}.",
        )

    # Collect recent actions across all ticks for this character.
    # Query all actions up to latest tick, filter by character, take last N.
    all_action_rows = repo.get_actions_in_range(0, latest)
    char_actions = [r for r in all_action_rows if r.character_id == character_id]
    recent_action_rows = char_actions[-recent:]

    recent_actions = [
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
        for row in recent_action_rows
    ]

    logger.debug(
        "GET /character/%s: tick=%d recent_actions=%d",
        character_id,
        latest,
        len(recent_actions),
    )

    return CharacterDetailResponse(
        character=_row_to_item(char_row),
        background=char_row.background,
        appearance=char_row.appearance,
        personality=char_row.personality,
        routine=dict(char_row.routine) if char_row.routine else {},
        recent_actions=recent_actions,
    )
