"""inkfish.storage.snapshot — SnapshotManager: save / reset / list / load_world.

Design rules:
- save_snapshot() and reset() both execute in a single SQLAlchemy transaction
  (SQLite WAL guarantees atomicity on crash).
- reset(to_tick_id) deletes actions/characters/locations/snapshots WHERE
  tick_id > to_tick_id.  llm_logs are NEVER deleted — they are a permanent
  cost/debug audit trail that must survive resets.
- load_world() rebuilds an in-memory WorldState from stored rows so the
  scheduler can resume from any historical tick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from inkfish.world.state import Character, Location, WorldState

from .models import ActionRow, CharacterRow, LocationRow, SnapshotRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SnapshotInfo:
    """Lightweight summary of a persisted snapshot (no character/action data)."""

    tick_id: int
    timestamp: datetime
    parent_tick_id: int | None
    char_count: int
    action_count: int


class SnapshotManager:
    """Manages the full-state snapshot lifecycle for the simulation timeline.

    Args:
        session_factory: A bound :class:`~sqlalchemy.orm.sessionmaker` produced
            by :func:`inkfish.storage.db.make_session_factory`.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        world: WorldState,
        tick_id: int,
        action_count: int,
        parent_tick_id: int | None = None,
    ) -> None:
        """Persist all characters and locations for *tick_id*, then write the index row.

        Actions are written by :meth:`Repository.save_action` during the tick;
        this method does NOT touch the actions table.  ``action_count`` is
        recorded in the metadata row only.

        The entire operation runs in a single transaction — either all rows
        land or none do.
        """
        with self._sf() as session:
            # 1. Upsert characters
            for char in world.characters:
                row = CharacterRow(
                    id=char.id,
                    tick_id=tick_id,
                    name=char.name,
                    mbti=char.mbti,
                    age=char.age,
                    background=char.background,
                    appearance=char.appearance,
                    personality=char.personality,
                    current_location=char.current_location,
                    current_mood=char.current_mood,
                    routine=char.routine,
                    weight=char.weight,
                    alive=char.alive,
                    death_summary=char.death_summary,
                    appearance_count=char.appearance_count,
                    last_active_tick=char.last_active_tick,
                    skipped_ticks=char.skipped_ticks,
                )
                session.merge(row)

            # 2. Upsert locations
            for loc in world.locations:
                row_loc = LocationRow(
                    id=loc.id,
                    tick_id=tick_id,
                    name=loc.name,
                    description=loc.description,
                    layer=loc.layer,
                    present_characters=list(loc.present_characters),
                    connected_to=list(loc.connected_to),
                    created_at_tick=loc.created_at_tick,
                    created_by=loc.created_by,
                )
                session.merge(row_loc)

            # 3. Insert snapshot index
            snap = SnapshotRow(
                tick_id=tick_id,
                timestamp=datetime.now(UTC),
                parent_tick_id=parent_tick_id,
                char_count=len(world.characters),
                action_count=action_count,
            )
            session.merge(snap)

            session.commit()

        logger.info(
            "Snapshot saved: tick=%d chars=%d actions=%d parent=%s",
            tick_id,
            len(world.characters),
            action_count,
            parent_tick_id,
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self, to_tick_id: int) -> None:
        """Delete all simulation rows strictly after *to_tick_id*.

        Tables affected (in dependency order):
            actions, characters, locations, snapshots

        ``llm_logs`` is intentionally excluded — it is a permanent audit trail
        for cost accounting and cross-reset experiment comparisons.

        Args:
            to_tick_id: Keep rows with ``tick_id <= to_tick_id``.
                Pass ``-1`` to wipe all simulation data.
        """
        with self._sf() as session:
            for model in (ActionRow, CharacterRow, LocationRow, SnapshotRow):
                stmt = delete(model).where(model.tick_id > to_tick_id)  # type: ignore[union-attr]
                session.execute(stmt)
                logger.debug(
                    "reset: deleted rows from %s where tick_id > %d",
                    model.__tablename__,  # type: ignore[union-attr]
                    to_tick_id,
                )
            session.commit()

        logger.info("Timeline reset to tick_id=%d (llm_logs preserved)", to_tick_id)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_snapshots(self) -> list[SnapshotInfo]:
        """Return metadata for all snapshots, sorted by tick_id ascending."""
        with self._sf() as session:
            result = session.execute(
                select(SnapshotRow).order_by(SnapshotRow.tick_id)
            )
            rows = result.scalars().all()
            return [
                SnapshotInfo(
                    tick_id=r.tick_id,
                    timestamp=r.timestamp,
                    parent_tick_id=r.parent_tick_id,
                    char_count=r.char_count,
                    action_count=r.action_count,
                )
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_world(self, tick_id: int) -> WorldState:
        """Rebuild an in-memory :class:`~inkfish.world.state.WorldState` from stored rows.

        Args:
            tick_id: The tick to reconstruct.

        Returns:
            A :class:`WorldState` populated with :class:`Character` and
            :class:`Location` objects matching the stored state at *tick_id*.

        Raises:
            KeyError: If no snapshot exists for *tick_id*.
        """
        with self._sf() as session:
            # Verify snapshot exists
            snap = session.get(SnapshotRow, tick_id)
            if snap is None:
                raise KeyError(f"No snapshot found for tick_id={tick_id}")

            char_rows = list(
                session.execute(
                    select(CharacterRow).where(CharacterRow.tick_id == tick_id)
                ).scalars()
            )
            loc_rows = list(
                session.execute(
                    select(LocationRow).where(LocationRow.tick_id == tick_id)
                ).scalars()
            )

            # Reconstruct sim_time from snapshot timestamp (approximate)
            # P0: use snapshot timestamp as a proxy; P5 will persist sim_time explicitly.
            characters = [
                Character(
                    id=r.id,
                    name=r.name,
                    mbti=r.mbti,
                    age=r.age,
                    background=r.background,
                    appearance=r.appearance,
                    personality=r.personality,
                    current_location=r.current_location,
                    current_mood=r.current_mood,
                    routine=dict(r.routine) if r.routine else {},
                    weight=r.weight,
                    alive=r.alive,
                    death_summary=r.death_summary,
                    appearance_count=r.appearance_count,
                    last_active_tick=r.last_active_tick,
                    skipped_ticks=r.skipped_ticks,
                )
                for r in char_rows
            ]
            locations = [
                Location(
                    id=r.id,
                    name=r.name,
                    description=r.description,
                    layer=r.layer,
                    present_characters=list(r.present_characters or []),
                    connected_to=list(r.connected_to or []),
                    created_at_tick=r.created_at_tick,
                    created_by=r.created_by,
                )
                for r in loc_rows
            ]

        world = WorldState(tick_id=tick_id, characters=characters, locations=locations)
        logger.info(
            "Loaded world at tick=%d: %d chars, %d locs",
            tick_id,
            len(characters),
            len(locations),
        )
        return world

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_latest_tick_id(self) -> int | None:
        """Return the highest tick_id in the snapshots table, or None."""
        with self._sf() as session:
            result = session.execute(select(func.max(SnapshotRow.tick_id)))
            return result.scalar_one_or_none()
