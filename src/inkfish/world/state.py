"""inkfish.world.state — In-memory world view shared by snapshot, repo, and scheduler.

P0: pure data containers plus a small set of query helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


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
    sim_time: datetime = field(default_factory=lambda: datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC))
    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    tick_interval_hours: int = 1  # P0: 1 tick == 1 simulated hour

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_character(self, char_id: str) -> Character | None:
        """Return the character with *char_id*, or ``None`` if not found."""
        for c in self.characters:
            if c.id == char_id:
                return c
        return None

    def get_location(self, loc_id: str) -> Location | None:
        """Return the location with *loc_id*, or ``None`` if not found."""
        for loc in self.locations:
            if loc.id == loc_id:
                return loc
        return None

    def characters_at_location(self, loc_id: str) -> list[Character]:
        """Return all alive characters whose ``current_location`` matches *loc_id*."""
        return [c for c in self.characters if c.current_location == loc_id and c.alive]

    def advance_time(self, hours: int) -> None:
        """Advance ``sim_time`` by *hours* and ``tick_id`` by *hours* / ``tick_interval_hours``.

        P0: ``tick_interval_hours == 1``, so ``advance_time(2)`` adds 2 ticks and 2 hours.
        """
        self.sim_time = self.sim_time + timedelta(hours=hours)
        self.tick_id += hours // self.tick_interval_hours
