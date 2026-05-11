"""inkfish.api.schemas — API request/response Pydantic DTOs.

These are distinct from the LLM contract types in inkfish.character.schema.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    phase: str
    latest_tick: int | None
    sim_running: bool


class StartSimulationRequest(BaseModel):
    n_ticks: int = Field(ge=1, le=1000)
    from_tick: int | None = None
    premise: str | None = None  # P5 stub; ignored in P0


class StartSimulationResponse(BaseModel):
    task_id: str
    started_at: datetime
    n_ticks: int
    from_tick: int


class PauseRequest(BaseModel):
    reason: str = "user-requested"


class ResetRequest(BaseModel):
    tick_id: int = Field(ge=-1, description="-1 to wipe all simulation data (llm_logs preserved)")


class ResetResponse(BaseModel):
    reset_to_tick: int
    rows_deleted: int  # informational, may be -1 if uncomputed


class TickActionItem(BaseModel):
    id: str
    character_id: str
    action_type: str
    content: str
    target: str | None
    mood: str
    inner_thought: str
    triggers_interaction: bool
    created_at: datetime


class TickResponse(BaseModel):
    tick_id: int
    timestamp: datetime | None
    parent_tick_id: int | None
    char_count: int
    action_count: int
    actions: list[TickActionItem]


class SnapshotItem(BaseModel):
    tick_id: int
    timestamp: datetime
    parent_tick_id: int | None
    char_count: int
    action_count: int


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotItem]


class CharacterItem(BaseModel):
    id: str
    name: str
    mbti: str
    age: int
    current_location: str
    current_mood: str
    weight: float
    alive: bool
    appearance_count: int
    last_active_tick: int


class CharacterListResponse(BaseModel):
    tick_id: int
    characters: list[CharacterItem]


class CharacterDetailResponse(BaseModel):
    character: CharacterItem
    background: str
    appearance: str
    personality: str
    routine: dict  # type: ignore[type-arg]
    recent_actions: list[TickActionItem]


class ErrorResponse(BaseModel):
    detail: str
