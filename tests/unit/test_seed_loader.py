"""Unit tests for inkfish.world.seed_loader and WorldState helpers (D6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inkfish.storage.db import make_session_factory
from inkfish.storage.models import CharacterRow, LocationRow, SnapshotRow
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
from inkfish.world.seed_loader import load_seed_file, seed_world
from inkfish.world.state import WorldState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo_and_snap(engine):  # type: ignore[no-untyped-def]
    sf = make_session_factory(engine)
    return Repository(sf), SnapshotManager(sf)


# ---------------------------------------------------------------------------
# 1. Basic load
# ---------------------------------------------------------------------------


def test_load_seed_file_returns_valid_world_state(repo_root: Path) -> None:
    world = load_seed_file(repo_root / "data" / "seed" / "world.json")
    assert isinstance(world, WorldState)
    assert world.tick_id == 0
    assert len(world.characters) == 5
    assert len(world.locations) == 1


# ---------------------------------------------------------------------------
# 2. Persona size threshold (DeepSeek prefix cache ~1024 tokens per persona)
# ---------------------------------------------------------------------------


def test_seed_personas_meet_size_threshold(repo_root: Path) -> None:
    world = load_seed_file(repo_root / "data" / "seed" / "world.json")
    for c in world.characters:
        assert (
            len(c.background) >= 400
        ), f"{c.id} ({c.name}) background too short: {len(c.background)} chars"
        assert (
            len(c.personality) >= 150
        ), f"{c.id} ({c.name}) personality too short: {len(c.personality)} chars"
        assert (
            len(c.appearance) >= 80
        ), f"{c.id} ({c.name}) appearance too short: {len(c.appearance)} chars"


# ---------------------------------------------------------------------------
# 3. MBTI archetypes match plan
# ---------------------------------------------------------------------------


def test_seed_mbti_archetypes_match_plan(repo_root: Path) -> None:
    world = load_seed_file(repo_root / "data" / "seed" / "world.json")
    expected = {"ENFP", "INTP", "ESTP", "ISFJ", "ENTJ"}
    actual = {c.mbti for c in world.characters}
    assert actual == expected, f"MBTI set mismatch: {actual}"


# ---------------------------------------------------------------------------
# 4. All characters at coffee shop
# ---------------------------------------------------------------------------


def test_seed_all_characters_at_coffee_shop(repo_root: Path) -> None:
    world = load_seed_file(repo_root / "data" / "seed" / "world.json")
    for c in world.characters:
        assert (
            c.current_location == "loc_coffee"
        ), f"{c.id} ({c.name}) is at '{c.current_location}', expected 'loc_coffee'"


# ---------------------------------------------------------------------------
# 5. seed_world persists to DB
# ---------------------------------------------------------------------------


def test_seed_world_persists_to_db(tmp_db_engine) -> None:  # type: ignore[no-untyped-def]
    repo, snapshots = _make_repo_and_snap(tmp_db_engine)
    seed_path = Path(__file__).parent.parent.parent / "data" / "seed" / "world.json"

    seed_world(seed_path, repo, snapshots)

    # Query DB directly
    sf = make_session_factory(tmp_db_engine)
    with sf() as session:
        char_rows = session.query(CharacterRow).filter_by(tick_id=0).all()
        loc_rows = session.query(LocationRow).filter_by(tick_id=0).all()
        snap_rows = session.query(SnapshotRow).filter_by(tick_id=0).all()

    assert len(char_rows) == 5, f"Expected 5 character rows, got {len(char_rows)}"
    assert len(loc_rows) == 1, f"Expected 1 location row, got {len(loc_rows)}"
    assert len(snap_rows) == 1, f"Expected 1 snapshot row, got {len(snap_rows)}"
    assert snap_rows[0].char_count == 5


# ---------------------------------------------------------------------------
# 6. seed_world clears existing data
# ---------------------------------------------------------------------------


def test_seed_world_clears_existing_data(tmp_db_engine) -> None:  # type: ignore[no-untyped-def]
    from inkfish.storage.models import CharacterRow as CR

    repo, snapshots = _make_repo_and_snap(tmp_db_engine)
    seed_path = Path(__file__).parent.parent.parent / "data" / "seed" / "world.json"

    # Pre-populate stale tick=5 data
    sf = make_session_factory(tmp_db_engine)
    with sf() as session:
        stale_char = CR(
            id="char_stale",
            tick_id=5,
            name="Stale",
            mbti="INTJ",
            age=30,
            background="x" * 50,
            appearance="y" * 30,
            personality="z" * 30,
            current_location="loc_coffee",
            current_mood="neutral",
            routine={},
            weight=1.0,
            alive=True,
            death_summary=None,
            appearance_count=0,
            last_active_tick=5,
            skipped_ticks=0,
        )
        session.add(stale_char)
        session.commit()

    # seed_world should wipe everything before writing tick_id=0
    seed_world(seed_path, repo, snapshots)

    with sf() as session:
        stale = session.query(CR).filter_by(id="char_stale").all()
        tick5 = session.query(CR).filter(CR.tick_id > 0).all()

    assert len(stale) == 0, "Stale character should have been wiped"
    assert len(tick5) == 0, "No rows with tick_id > 0 should remain after seed"


# ---------------------------------------------------------------------------
# 7. Malformed seed — missing required field
# ---------------------------------------------------------------------------


def test_seed_malformed_missing_field_raises(tmp_path: Path, repo_root: Path) -> None:
    seed_path = repo_root / "data" / "seed" / "world.json"
    with seed_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    # Remove mbti from first character
    del data["characters"][0]["mbti"]

    bad_seed = tmp_path / "bad_seed.json"
    bad_seed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="mbti"):
        load_seed_file(bad_seed)


# ---------------------------------------------------------------------------
# 8. Malformed seed — invalid MBTI value
# ---------------------------------------------------------------------------


def test_seed_malformed_invalid_mbti_raises(tmp_path: Path, repo_root: Path) -> None:
    seed_path = repo_root / "data" / "seed" / "world.json"
    with seed_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    data["characters"][0]["mbti"] = "XXXX"

    bad_seed = tmp_path / "bad_mbti.json"
    bad_seed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="XXXX"):
        load_seed_file(bad_seed)


# ---------------------------------------------------------------------------
# 9. WorldState.get_character
# ---------------------------------------------------------------------------


def test_world_state_get_character(seed_world_state: WorldState) -> None:
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    assert char.name == "林夏"
    assert char.mbti == "ENFP"

    missing = seed_world_state.get_character("char_does_not_exist")
    assert missing is None


# ---------------------------------------------------------------------------
# 10. WorldState.characters_at_location
# ---------------------------------------------------------------------------


def test_world_state_characters_at_location(seed_world_state: WorldState) -> None:
    chars = seed_world_state.characters_at_location("loc_coffee")
    assert len(chars) == 5
    ids = {c.id for c in chars}
    assert ids == {"char_lin", "char_zhao", "char_chen", "char_wang", "char_li"}


# ---------------------------------------------------------------------------
# 11. WorldState.advance_time
# ---------------------------------------------------------------------------


def test_world_state_advance_time_increments_tick_and_time(
    seed_world_state: WorldState,
) -> None:
    initial_tick = seed_world_state.tick_id
    initial_time = seed_world_state.sim_time

    seed_world_state.advance_time(2)

    assert seed_world_state.tick_id == initial_tick + 2
    from datetime import timedelta

    assert seed_world_state.sim_time == initial_time + timedelta(hours=2)
