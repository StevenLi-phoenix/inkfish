"""inkfish.storage.models — SQLAlchemy 2.0 ORM models (M1 Storage).

Snapshot strategy: composite PK (id, tick_id) on characters and locations.
Each tick writes a complete copy of the state — no diffs, no JSON blobs.
This lets P1+ query "who was at location X at tick T" with a single SQL
WHERE clause, and lets P5 reset use a single DELETE WHERE tick_id > :t.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all INKFISH ORM models."""


class CharacterRow(Base):
    """One row per (character, tick) — composite PK enables per-tick snapshots.

    Indexed by (id, tick_id) so queries like
    "state of character X at tick T" are O(log n) without a full scan.
    """

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(primary_key=True)
    tick_id: Mapped[int] = mapped_column(primary_key=True)

    # Identity
    name: Mapped[str]
    mbti: Mapped[str]
    age: Mapped[int]

    # Long-form text fields
    background: Mapped[str] = mapped_column(Text)
    appearance: Mapped[str] = mapped_column(Text)
    personality: Mapped[str] = mapped_column(Text)

    # Dynamic state
    current_location: Mapped[str]
    current_mood: Mapped[str]
    routine: Mapped[dict] = mapped_column(JSON, default=dict)

    # Weight / lifecycle
    weight: Mapped[float] = mapped_column(default=1.0)
    alive: Mapped[bool] = mapped_column(default=True)
    death_summary: Mapped[str | None] = mapped_column(Text, default=None)

    # Appearance tracking (for weight decay and scheduler)
    appearance_count: Mapped[int] = mapped_column(default=0)
    last_active_tick: Mapped[int] = mapped_column(default=0)
    skipped_ticks: Mapped[int] = mapped_column(default=0)

    def __repr__(self) -> str:
        return f"<CharacterRow id={self.id!r} tick={self.tick_id} name={self.name!r}>"


class ActionRow(Base):
    """One row per LLM-generated character action.

    PK is a uuid4 string so multiple actions per (character, tick) are valid
    (e.g., interaction rounds produce several sub-actions in one tick).
    """

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(primary_key=True)  # uuid4 string
    tick_id: Mapped[int] = mapped_column(index=True)
    character_id: Mapped[str] = mapped_column(index=True)

    action_type: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None]
    mood: Mapped[str]
    inner_thought: Mapped[str] = mapped_column(Text, default="")
    triggers_interaction: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<ActionRow id={self.id!r} tick={self.tick_id}"
            f" char={self.character_id!r} type={self.action_type!r}>"
        )


class LocationRow(Base):
    """One row per (location, tick) — same composite-PK snapshot strategy as CharacterRow.

    ``present_characters`` and ``connected_to`` are JSON lists, updated each tick
    to reflect the current spatial state.  The ``layer`` column is physical-only in
    P0 but included now so P7 multi-layer worlds don't need a schema migration.
    """

    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(primary_key=True)
    tick_id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    layer: Mapped[str] = mapped_column(default="physical")

    present_characters: Mapped[list] = mapped_column(JSON, default=list)
    connected_to: Mapped[list] = mapped_column(JSON, default=list)

    created_at_tick: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[str] = mapped_column(default="system")

    def __repr__(self) -> str:
        return f"<LocationRow id={self.id!r} tick={self.tick_id} name={self.name!r}>"


class SnapshotRow(Base):
    """One row per completed tick — the snapshot index.

    ``parent_tick_id`` is NULL for the root timeline and points to the fork
    origin when a ``SnapshotManager.fork()`` branch was taken (P5+).
    """

    __tablename__ = "snapshots"

    tick_id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    parent_tick_id: Mapped[int | None] = mapped_column(default=None)
    char_count: Mapped[int]
    action_count: Mapped[int]

    def __repr__(self) -> str:
        return (
            f"<SnapshotRow tick={self.tick_id}"
            f" chars={self.char_count} actions={self.action_count}>"
        )


class LLMLogRow(Base):
    """Immutable audit log for every LLM call — never deleted, even after reset().

    Design rule: every LLM call MUST produce a row here before the caller
    inspects the response.  Parsing can be re-run for free; lost raw data
    costs real money and breaks cost / cache-hit auditing.

    ``cached_tokens`` maps to DeepSeek's ``prompt_cache_hit_tokens``.
    ``attempt`` is 1-based (1..max_retries) so logs show which retry succeeded.
    """

    __tablename__ = "llm_logs"

    id: Mapped[str] = mapped_column(primary_key=True)  # uuid4 string
    tick_id: Mapped[int] = mapped_column(index=True)
    character_id: Mapped[str | None] = mapped_column(index=True)

    provider: Mapped[str]
    model: Mapped[str]

    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)

    prompt_tokens: Mapped[int] = mapped_column(default=0)
    response_tokens: Mapped[int] = mapped_column(default=0)
    cached_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    finish_reason: Mapped[str] = mapped_column(default="")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    attempt: Mapped[int] = mapped_column(default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"<LLMLogRow id={self.id!r} tick={self.tick_id}"
            f" model={self.model!r} attempt={self.attempt}>"
        )
