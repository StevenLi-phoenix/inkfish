"""Unit tests for SnapshotManager and Repository — D3.

All tests use the in-memory SQLite engine from conftest.py (no LLM calls).
Each test function is fully isolated — a fresh engine per function.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine

from inkfish.storage.db import make_session_factory
from inkfish.storage.models import ActionRow, LLMLogRow
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
from inkfish.world.state import Character, Location, WorldState

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_character(suffix: str = "", *, location: str = "loc-1") -> Character:
    return Character(
        id=f"char-{suffix or uuid.uuid4().hex[:8]}",
        name=f"Name_{suffix}",
        mbti="INTP",
        age=25,
        background="A background story.",
        appearance="Dark hair, medium build.",
        personality="Quiet and analytical.",
        current_location=location,
        current_mood="calm",
        routine={"morning": "coffee"},
        weight=1.0,
        alive=True,
    )


def _make_location(suffix: str = "") -> Location:
    return Location(
        id=f"loc-{suffix or uuid.uuid4().hex[:8]}",
        name=f"Place_{suffix}",
        description="A cozy place.",
        layer="physical",
        present_characters=[],
        connected_to=[],
        created_at_tick=0,
        created_by="system",
    )


def _make_action(
    tick_id: int, character_id: str = "char-1", *, action_type: str = "THINK"
) -> ActionRow:
    return ActionRow(
        id=str(uuid.uuid4()),
        tick_id=tick_id,
        character_id=character_id,
        action_type=action_type,
        content="I ponder life.",
        target=None,
        mood="calm",
        inner_thought="deep thoughts",
        triggers_interaction=False,
        created_at=datetime.now(UTC),
    )


def _make_llm_log(tick_id: int, character_id: str = "char-1") -> LLMLogRow:
    return LLMLogRow(
        id=str(uuid.uuid4()),
        tick_id=tick_id,
        character_id=character_id,
        provider="deepseek",
        model="deepseek-v4-pro",
        prompt="System prompt here.",
        response='{"action_type":"THINK","content":"thinking"}',
        prompt_tokens=100,
        response_tokens=50,
        cached_tokens=80,
        cost_usd=0.001,
        latency_ms=500,
        finish_reason="stop",
        error=None,
        attempt=1,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_world() -> WorldState:
    """Return a hand-built WorldState with 3 characters and 1 location."""
    chars = [_make_character(f"A{i}") for i in range(3)]
    locs = [_make_location("L1")]
    return WorldState(tick_id=0, characters=chars, locations=locs)


@pytest.fixture
def snap_mgr(in_memory_engine: Engine) -> SnapshotManager:
    sf = make_session_factory(in_memory_engine)
    return SnapshotManager(sf)


@pytest.fixture
def repo(in_memory_engine: Engine) -> Repository:
    sf = make_session_factory(in_memory_engine)
    return Repository(sf)


@pytest.fixture
def snap_and_repo(in_memory_engine: Engine) -> tuple[SnapshotManager, Repository]:
    sf = make_session_factory(in_memory_engine)
    return SnapshotManager(sf), Repository(sf)


# ---------------------------------------------------------------------------
# Test 1 — save_snapshot persists chars, locations, and snapshot meta
# ---------------------------------------------------------------------------


def test_save_snapshot_persists_characters_locations_and_meta(
    snap_mgr: SnapshotManager, repo: Repository, fake_world: WorldState
) -> None:
    snap_mgr.save_snapshot(fake_world, tick_id=0, action_count=5)

    chars = repo.get_characters_at_tick(0)
    locs = repo.get_locations_at_tick(0)
    snap = repo.get_snapshot_meta(0)

    assert len(chars) == 3
    assert len(locs) == 1
    assert snap is not None
    assert snap.tick_id == 0
    assert snap.char_count == 3
    assert snap.action_count == 5


# ---------------------------------------------------------------------------
# Test 2 — independent rows at multiple ticks (composite PK)
# ---------------------------------------------------------------------------


def test_save_snapshot_at_multiple_ticks_creates_independent_rows(
    snap_mgr: SnapshotManager, repo: Repository, fake_world: WorldState
) -> None:
    for tick in range(3):
        snap_mgr.save_snapshot(fake_world, tick_id=tick, action_count=2)

    for tick in range(3):
        assert len(repo.get_characters_at_tick(tick)) == 3
        assert len(repo.get_locations_at_tick(tick)) == 1

    # Total rows: 3 ticks × 3 chars = 9 character rows
    all_chars: list = []
    for tick in range(3):
        all_chars.extend(repo.get_characters_at_tick(tick))
    assert len(all_chars) == 9


# ---------------------------------------------------------------------------
# Test 3 — load_world reconstructs the correct tick version
# ---------------------------------------------------------------------------


def test_load_world_reconstructs_state(snap_mgr: SnapshotManager, fake_world: WorldState) -> None:
    # Save tick=5 with original mood
    world_5 = WorldState(
        tick_id=5,
        characters=[_make_character("X1"), _make_character("X2")],
        locations=[_make_location("Z")],
    )
    world_5.characters[0].current_mood = "happy"
    snap_mgr.save_snapshot(world_5, tick_id=5, action_count=3)

    # Mutate and save tick=6 with different mood
    world_6 = WorldState(
        tick_id=6,
        characters=[_make_character("X1"), _make_character("X2")],
        locations=[_make_location("Z")],
    )
    world_6.characters[0].current_mood = "sad"
    snap_mgr.save_snapshot(world_6, tick_id=6, action_count=4)

    loaded = snap_mgr.load_world(5)
    assert loaded.tick_id == 5
    assert len(loaded.characters) == 2
    # Find the character with id matching world_5.characters[0].id
    c0_id = world_5.characters[0].id
    matched = next(c for c in loaded.characters if c.id == c0_id)
    assert matched.current_mood == "happy"


# ---------------------------------------------------------------------------
# Test 4 — list_snapshots returns all ticks sorted
# ---------------------------------------------------------------------------


def test_list_snapshots_returns_all_ticks_sorted(
    snap_mgr: SnapshotManager, fake_world: WorldState
) -> None:
    for tick in [2, 0, 1]:
        snap_mgr.save_snapshot(fake_world, tick_id=tick, action_count=tick * 2)

    infos = snap_mgr.list_snapshots()
    assert len(infos) == 3
    assert [i.tick_id for i in infos] == [0, 1, 2]
    assert infos[1].action_count == 2  # tick=1 has action_count=2
    assert infos[2].action_count == 4  # tick=2 has action_count=4


# ---------------------------------------------------------------------------
# Test 5 — reset deletes rows beyond tick, preserves rows at/before tick
# ---------------------------------------------------------------------------


def test_reset_deletes_rows_beyond_tick(
    snap_and_repo: tuple[SnapshotManager, Repository], fake_world: WorldState
) -> None:
    snap_mgr, repo = snap_and_repo

    # Save 5 ticks of snapshots + actions
    for tick in range(5):
        snap_mgr.save_snapshot(fake_world, tick_id=tick, action_count=1)
        repo.save_action(_make_action(tick))

    snap_mgr.reset(to_tick_id=2)

    # Rows at tick <= 2 must survive
    for tick in range(3):
        assert len(repo.get_characters_at_tick(tick)) == 3
        assert len(repo.get_locations_at_tick(tick)) == 1
        assert len(repo.get_actions_at_tick(tick)) == 1
        assert repo.get_snapshot_meta(tick) is not None

    # Rows at tick > 2 must be gone
    for tick in range(3, 5):
        assert len(repo.get_characters_at_tick(tick)) == 0
        assert len(repo.get_locations_at_tick(tick)) == 0
        assert len(repo.get_actions_at_tick(tick)) == 0
        assert repo.get_snapshot_meta(tick) is None


# ---------------------------------------------------------------------------
# Test 6 — reset preserves llm_logs (cost-audit invariant)
# ---------------------------------------------------------------------------


def test_reset_preserves_llm_logs(
    snap_and_repo: tuple[SnapshotManager, Repository], fake_world: WorldState
) -> None:
    snap_mgr, repo = snap_and_repo

    # Save snapshots at ticks 0–5 and an LLM log at tick=5
    for tick in range(6):
        snap_mgr.save_snapshot(fake_world, tick_id=tick, action_count=0)
    llm_log = _make_llm_log(tick_id=5)
    repo.log_llm(llm_log)

    snap_mgr.reset(to_tick_id=2)

    # The LLM log must still exist
    logs = repo.get_llm_logs()
    assert len(logs) == 1
    assert logs[0].id == llm_log.id


# ---------------------------------------------------------------------------
# Test 7 — reset(-1) wipes all simulation data but not llm_logs
# ---------------------------------------------------------------------------


def test_reset_to_negative_tick_clears_all_simulation_data(
    snap_and_repo: tuple[SnapshotManager, Repository], fake_world: WorldState
) -> None:
    snap_mgr, repo = snap_and_repo

    snap_mgr.save_snapshot(fake_world, tick_id=0, action_count=1)
    repo.save_action(_make_action(0))
    repo.log_llm(_make_llm_log(tick_id=0))

    snap_mgr.reset(to_tick_id=-1)

    assert len(repo.get_characters_at_tick(0)) == 0
    assert len(repo.get_locations_at_tick(0)) == 0
    assert len(repo.get_actions_at_tick(0)) == 0
    assert repo.get_snapshot_meta(0) is None
    # LLM log survives
    assert len(repo.get_llm_logs()) == 1


# ---------------------------------------------------------------------------
# Test 8 — save_snapshot records parent_tick_id in the metadata row
# ---------------------------------------------------------------------------


def test_save_snapshot_with_parent_tick_id(
    snap_mgr: SnapshotManager, repo: Repository, fake_world: WorldState
) -> None:
    snap_mgr.save_snapshot(fake_world, tick_id=10, action_count=0, parent_tick_id=3)
    snap = repo.get_snapshot_meta(10)
    assert snap is not None
    assert snap.parent_tick_id == 3


# ---------------------------------------------------------------------------
# Test 9 — repository upsert handles same PK twice without IntegrityError
# ---------------------------------------------------------------------------


def test_repository_upsert_handles_same_pk_twice(repo: Repository) -> None:
    char = _make_character("DUP")
    repo.upsert_character(char, tick_id=0)

    # Mutate mood and upsert again with the same (id, tick_id)
    char.current_mood = "excited"
    repo.upsert_character(char, tick_id=0)

    rows = repo.get_characters_at_tick(0)
    assert len(rows) == 1
    assert rows[0].current_mood == "excited"


# ---------------------------------------------------------------------------
# Test 10 — repository save_action round-trip
# ---------------------------------------------------------------------------


def test_repository_save_action_round_trip(repo: Repository) -> None:
    action = _make_action(tick_id=7, character_id="char-Z", action_type="SPEAK")
    action.content = "Hello world!"
    action.target = "char-W"
    action.mood = "cheerful"
    repo.save_action(action)

    rows = repo.get_actions_at_tick(7)
    assert len(rows) == 1
    r = rows[0]
    assert r.id == action.id
    assert r.character_id == "char-Z"
    assert r.action_type == "SPEAK"
    assert r.content == "Hello world!"
    assert r.target == "char-W"
    assert r.mood == "cheerful"


# ---------------------------------------------------------------------------
# Test 11 — repository log_llm round-trip (all fields)
# ---------------------------------------------------------------------------


def test_repository_log_llm_round_trip(repo: Repository) -> None:
    log = _make_llm_log(tick_id=3, character_id="char-A")
    log.cached_tokens = 42
    log.cost_usd = 0.00123
    log.latency_ms = 312
    log.finish_reason = "stop"
    log.error = None
    log.attempt = 2
    repo.log_llm(log)

    logs = repo.get_llm_logs(tick_id=3)
    assert len(logs) == 1
    r = logs[0]
    assert r.id == log.id
    assert r.character_id == "char-A"
    assert r.provider == "deepseek"
    assert r.model == "deepseek-v4-pro"
    assert r.cached_tokens == 42
    assert abs(r.cost_usd - 0.00123) < 1e-9
    assert r.latency_ms == 312
    assert r.attempt == 2
    assert r.error is None


# ---------------------------------------------------------------------------
# Test 12 — get_actions_in_range returns inclusive range
# ---------------------------------------------------------------------------


def test_get_actions_in_range(repo: Repository) -> None:
    for tick in range(1, 6):  # ticks 1..5
        repo.save_action(_make_action(tick))

    # Range 2..4 (inclusive) should return 3 actions
    results = repo.get_actions_in_range(start_tick=2, end_tick=4)
    assert len(results) == 3
    tick_ids = sorted(r.tick_id for r in results)
    assert tick_ids == [2, 3, 4]
