"""inkfish.world.state — In-memory world view shared by snapshot, repo, and scheduler.

P0: pure data containers only. No behavior methods — those come in P1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Character:
    """In-memory mirror of CharacterRow.

    All fields match the ORM column names so snapshot/repo can map 1-to-1.
    """

    id: str
    name: str
    mbti: str
    age: int
    background: str
    appearance: str
    personality: str
    current_location: str
    current_mood: str
    routine: dict  # type: ignore[type-arg]
    weight: float = 1.0
    alive: bool = True
    death_summary: str | None = None
    appearance_count: int = 0
    last_active_tick: int = 0
    skipped_ticks: int = 0


@dataclass
class Location:
    """In-memory mirror of LocationRow."""

    id: str
    name: str
    description: str
    layer: str = "physical"
    present_characters: list[str] = field(default_factory=list)
    connected_to: list[str] = field(default_factory=list)
    created_at_tick: int = 0
    created_by: str = "system"


@dataclass
class WorldState:
    """In-memory view of the world at a given tick.

    Reconstructed from snapshots by SnapshotManager.load_world().
    The scheduler mutates this in-place during a tick, then passes it to
    SnapshotManager.save_snapshot() to persist the state.
    """

    tick_id: int = 0
    sim_time: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
    )
    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
