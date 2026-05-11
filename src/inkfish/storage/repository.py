"""inkfish.storage.repository — CRUD facade for the simulation database.

All write methods open, commit, and close their own session so callers
don't need to manage transaction boundaries.  Read methods use context-manager
sessions for clean resource handling.

The Repository does NOT own snapshot lifecycle — that belongs to SnapshotManager.
It is responsible for fine-grained writes (actions, llm_logs, individual rows)
and reads (queries by tick, by range, latest tick, etc.).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import ActionRow, CharacterRow, LLMLogRow, LocationRow, SnapshotRow

if TYPE_CHECKING:
    from inkfish.world.state import Character, Location

logger = logging.getLogger(__name__)


class Repository:
    """CRUD facade used by the scheduler and API layer.

    Args:
        session_factory: A bound :class:`~sqlalchemy.orm.sessionmaker` instance
            produced by :func:`inkfish.storage.db.make_session_factory`.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ------------------------------------------------------------------
    # Writes (each method owns its session/transaction)
    # ------------------------------------------------------------------

    def upsert_character(self, char: Character, tick_id: int) -> None:
        """Insert or replace the character row for *(char.id, tick_id)*.

        Uses ``Session.merge()`` so calling this twice with the same PK is
        safe — the second call silently overwrites the first.
        """
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
        with self._sf() as session:
            session.merge(row)
            session.commit()
        logger.debug("Upserted character %s at tick %d", char.id, tick_id)

    def upsert_location(self, loc: Location, tick_id: int) -> None:
        """Insert or replace the location row for *(loc.id, tick_id)*."""
        row = LocationRow(
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
        with self._sf() as session:
            session.merge(row)
            session.commit()
        logger.debug("Upserted location %s at tick %d", loc.id, tick_id)

    def save_action(self, action: ActionRow) -> None:
        """Persist an :class:`~inkfish.storage.models.ActionRow`."""
        # Capture identity fields before committing (commit expires ORM attrs).
        action_id = action.id
        action_type = action.action_type
        tick_id = action.tick_id
        character_id = action.character_id
        with self._sf() as session:
            session.add(action)
            session.commit()
        logger.debug(
            "Saved action %s (type=%s tick=%d char=%s)",
            action_id,
            action_type,
            tick_id,
            character_id,
        )

    def log_llm(self, log: LLMLogRow) -> None:
        """Persist an :class:`~inkfish.storage.models.LLMLogRow`.

        Rule: callers MUST call this before inspecting the LLM response so
        raw API data is durably recorded even if parsing fails.
        """
        # Capture fields before commit (commit expires ORM attrs on the instance).
        log_id = log.id
        log_tick = log.tick_id
        log_model = log.model
        log_attempt = log.attempt
        with self._sf() as session:
            session.add(log)
            session.commit()
        logger.debug(
            "Logged LLM call %s (tick=%d model=%s attempt=%d)",
            log_id,
            log_tick,
            log_model,
            log_attempt,
        )

    def save_snapshot_meta(
        self,
        tick_id: int,
        char_count: int,
        action_count: int,
        parent_tick_id: int | None = None,
    ) -> None:
        """Persist a :class:`~inkfish.storage.models.SnapshotRow` index entry."""
        row = SnapshotRow(
            tick_id=tick_id,
            timestamp=datetime.now(UTC),
            parent_tick_id=parent_tick_id,
            char_count=char_count,
            action_count=action_count,
        )
        with self._sf() as session:
            session.merge(row)
            session.commit()
        logger.debug(
            "Saved snapshot meta for tick %d (chars=%d actions=%d)",
            tick_id,
            char_count,
            action_count,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_characters_at_tick(self, tick_id: int) -> list[CharacterRow]:
        """Return all character rows snapshotted at *tick_id*."""
        with self._sf() as session:
            result = session.execute(
                select(CharacterRow).where(CharacterRow.tick_id == tick_id)
            )
            return list(result.scalars().all())

    def get_locations_at_tick(self, tick_id: int) -> list[LocationRow]:
        """Return all location rows snapshotted at *tick_id*."""
        with self._sf() as session:
            result = session.execute(
                select(LocationRow).where(LocationRow.tick_id == tick_id)
            )
            return list(result.scalars().all())

    def get_actions_at_tick(self, tick_id: int) -> list[ActionRow]:
        """Return all action rows for *tick_id*."""
        with self._sf() as session:
            result = session.execute(
                select(ActionRow).where(ActionRow.tick_id == tick_id)
            )
            return list(result.scalars().all())

    def get_actions_in_range(self, start_tick: int, end_tick: int) -> list[ActionRow]:
        """Return action rows where *start_tick* ≤ tick_id ≤ *end_tick* (inclusive)."""
        with self._sf() as session:
            result = session.execute(
                select(ActionRow).where(
                    ActionRow.tick_id >= start_tick,
                    ActionRow.tick_id <= end_tick,
                )
            )
            return list(result.scalars().all())

    def get_latest_tick_id(self) -> int | None:
        """Return the highest tick_id present in the snapshots table, or None."""
        with self._sf() as session:
            result = session.execute(select(func.max(SnapshotRow.tick_id)))
            return result.scalar_one_or_none()

    def get_snapshot_meta(self, tick_id: int) -> SnapshotRow | None:
        """Return the :class:`~inkfish.storage.models.SnapshotRow` for *tick_id*."""
        with self._sf() as session:
            return session.get(SnapshotRow, tick_id)

    def list_snapshots(self) -> list[SnapshotRow]:
        """Return all snapshot index rows, ordered by tick_id ascending."""
        with self._sf() as session:
            result = session.execute(
                select(SnapshotRow).order_by(SnapshotRow.tick_id)
            )
            return list(result.scalars().all())

    def get_llm_logs(self, tick_id: int | None = None) -> list[LLMLogRow]:
        """Return LLM log rows, optionally filtered by *tick_id*.

        If *tick_id* is None, all rows are returned ordered by created_at.
        """
        with self._sf() as session:
            stmt = select(LLMLogRow)
            if tick_id is not None:
                stmt = stmt.where(LLMLogRow.tick_id == tick_id)
            stmt = stmt.order_by(LLMLogRow.created_at)
            result = session.execute(stmt)
            return list(result.scalars().all())
