"""Unit tests for M1 Storage: ORM models, DB init, and WAL pragma.

All tests use in-memory SQLite except test #8 (WAL), which uses a real file
database because WAL mode is not supported for in-memory connections.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from inkfish.storage.db import make_session_factory
from inkfish.storage.models import (
    ActionRow,
    CharacterRow,
    LLMLogRow,
    LocationRow,
    SnapshotRow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_char(char_id: str, tick_id: int, **kwargs: object) -> CharacterRow:
    """Build a minimal CharacterRow with required fields."""
    defaults: dict[str, object] = {
        "name": "Test Character",
        "mbti": "INTP",
        "age": 25,
        "background": "A background.",
        "appearance": "An appearance.",
        "personality": "A personality.",
        "current_location": "loc_a",
        "current_mood": "neutral",
    }
    defaults.update(kwargs)
    return CharacterRow(id=char_id, tick_id=tick_id, **defaults)  # type: ignore[arg-type]


def _new_action(tick_id: int, char_id: str, **kwargs: object) -> ActionRow:
    """Build a minimal ActionRow with required fields."""
    defaults: dict[str, object] = {
        "action_type": "THINK",
        "content": "Thinking...",
        "mood": "calm",
    }
    defaults.update(kwargs)
    return ActionRow(id=str(uuid.uuid4()), tick_id=tick_id, character_id=char_id, **defaults)  # type: ignore[arg-type]


def _new_location(loc_id: str, tick_id: int, **kwargs: object) -> LocationRow:
    """Build a minimal LocationRow with required fields."""
    defaults: dict[str, object] = {
        "name": "Test Location",
        "description": "A description.",
    }
    defaults.update(kwargs)
    return LocationRow(id=loc_id, tick_id=tick_id, **defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 1 — all 5 tables are created by init_db
# ---------------------------------------------------------------------------


def test_init_db_creates_all_tables(in_memory_engine: object) -> None:
    """init_db must create all five expected tables."""
    engine = in_memory_engine  # already initted by fixture
    table_names = set(inspect(engine).get_table_names())
    expected = {"characters", "actions", "locations", "snapshots", "llm_logs"}
    assert expected == table_names, (
        f"Missing tables: {expected - table_names}. Extra: {table_names - expected}"
    )


# ---------------------------------------------------------------------------
# Test 2 — CharacterRow composite PK
# ---------------------------------------------------------------------------


def test_character_composite_pk(in_memory_engine: object) -> None:
    """Same char id at different tick_ids must coexist; duplicate (id, tick) fails."""
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]

    # Two different ticks — both should succeed
    with SessionLocal() as session:
        session.add(_new_char("char_a", 0))
        session.add(_new_char("char_a", 1))
        session.commit()

    with SessionLocal() as session:
        rows = session.query(CharacterRow).filter_by(id="char_a").all()
        assert len(rows) == 2, "Expected 2 rows for char_a across tick 0 and tick 1"

    # Duplicate (id, tick_id) must raise IntegrityError
    with SessionLocal() as session:
        session.add(_new_char("char_a", 0, name="Duplicate"))
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# Test 3 — LocationRow composite PK
# ---------------------------------------------------------------------------


def test_location_composite_pk(in_memory_engine: object) -> None:
    """Same location id at different tick_ids must coexist; duplicate (id, tick) fails."""
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]

    with SessionLocal() as session:
        session.add(_new_location("loc_1", 0))
        session.add(_new_location("loc_1", 1))
        session.commit()

    with SessionLocal() as session:
        rows = session.query(LocationRow).filter_by(id="loc_1").all()
        assert len(rows) == 2

    with SessionLocal() as session:
        session.add(_new_location("loc_1", 0, name="Duplicate"))
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# Test 4 — ActionRow PK is uuid, independent of (character_id, tick_id)
# ---------------------------------------------------------------------------


def test_action_pk_uuid_independent_of_tick(in_memory_engine: object) -> None:
    """Two distinct uuid PKs at same (character_id, tick_id) must both succeed.
    Reusing the same uuid must fail.
    """
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]
    fixed_id = str(uuid.uuid4())

    with SessionLocal() as session:
        session.add(_new_action(0, "char_x"))
        session.add(_new_action(0, "char_x"))  # different uuid generated each time
        session.commit()

    with SessionLocal() as session:
        rows = session.query(ActionRow).filter_by(character_id="char_x", tick_id=0).all()
        assert len(rows) == 2

    # Same uuid twice must fail
    with SessionLocal() as session:
        session.add(ActionRow(
            id=fixed_id, tick_id=0, character_id="char_x",
            action_type="THINK", content="First", mood="calm",
        ))
        session.commit()

    with SessionLocal() as session:
        session.add(ActionRow(
            id=fixed_id, tick_id=0, character_id="char_x",
            action_type="THINK", content="Duplicate", mood="calm",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# Test 5 — SnapshotRow tick_id is PK; duplicate tick_id fails
# ---------------------------------------------------------------------------


def test_snapshot_unique_per_tick(in_memory_engine: object) -> None:
    """tick_id is the primary key; inserting two rows for the same tick must fail."""
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]

    with SessionLocal() as session:
        session.add(SnapshotRow(tick_id=5, char_count=3, action_count=10))
        session.commit()

    with SessionLocal() as session:
        session.add(SnapshotRow(tick_id=5, char_count=99, action_count=99))
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# Test 6 — LLMLogRow full round-trip
# ---------------------------------------------------------------------------


def test_llm_log_round_trip(in_memory_engine: object) -> None:
    """Insert a fully-populated LLMLogRow and verify numeric fields survive the round-trip."""
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]
    log_id = str(uuid.uuid4())
    ts = datetime.now(UTC)

    with SessionLocal() as session:
        session.add(LLMLogRow(
            id=log_id,
            tick_id=3,
            character_id="char_b",
            provider="deepseek",
            model="deepseek-v4-pro",
            prompt="Hello",
            response='{"action_type":"THINK"}',
            prompt_tokens=120,
            response_tokens=45,
            cached_tokens=80,
            cost_usd=0.00123,
            latency_ms=512,
            finish_reason="stop",
            error=None,
            attempt=2,
            created_at=ts,
        ))
        session.commit()

    with SessionLocal() as session:
        row = session.get(LLMLogRow, log_id)
        assert row is not None, "LLMLogRow not found after insert"
        assert row.cached_tokens == 80
        assert abs(row.cost_usd - 0.00123) < 1e-9
        assert row.latency_ms == 512
        assert row.attempt == 2
        assert row.character_id == "char_b"
        assert row.error is None


# ---------------------------------------------------------------------------
# Test 7 — JSON columns round-trip
# ---------------------------------------------------------------------------


def test_json_columns_round_trip(in_memory_engine: object) -> None:
    """Verify that dict/list JSON columns survive a write → read cycle unchanged."""
    SessionLocal = make_session_factory(in_memory_engine)  # type: ignore[arg-type]
    routine_val = {"hours": [9, 17], "activity": "work"}
    present_val = ["char_a", "char_b"]
    connected_val = ["loc_2", "loc_3"]

    with SessionLocal() as session:
        session.add(_new_char("char_c", 0, routine=routine_val))
        session.add(_new_location(
            "loc_x", 0,
            present_characters=present_val,
            connected_to=connected_val,
        ))
        session.commit()

    with SessionLocal() as session:
        char = session.get(CharacterRow, ("char_c", 0))
        assert char is not None
        assert char.routine == routine_val, f"routine mismatch: {char.routine!r}"

        loc = session.get(LocationRow, ("loc_x", 0))
        assert loc is not None
        assert loc.present_characters == present_val
        assert loc.connected_to == connected_val


# ---------------------------------------------------------------------------
# Test 8 — WAL pragma is applied to file-backed SQLite
# ---------------------------------------------------------------------------


def test_wal_pragma_applied_to_file_db(tmp_db_engine: object) -> None:
    """PRAGMA journal_mode must return 'wal' for a file-backed SQLite database.

    This test MUST use a file database (not :memory:) because SQLite does not
    support WAL mode for in-memory connections.
    """
    engine = tmp_db_engine
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode;"))
        mode = result.scalar()
    assert mode == "wal", (
        f"Expected journal_mode='wal', got {mode!r}. "
        "Check that _apply_sqlite_pragmas listener is registered."
    )
