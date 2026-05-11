"""Unit tests for inkfish.tick.scheduler.

All LLM calls are intercepted by monkeypatching ``call_with_retry`` — the
real DeepSeek API is never contacted.  This verifies the scheduler's
orchestration logic in complete isolation.

Test design:
- ``_make_scripted_action`` builds a valid CharacterAction.
- ``_patch_call_with_retry`` monkeypatches the function with a plan dict
  keyed by (character_id, tick_id) → CharacterAction.  Any key not in the
  plan returns a DO_NOTHING fallback.
- Each test creates an in-memory SQLite DB + world from the canonical seed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.character.validator import fallback_do_nothing
from inkfish.storage.db import create_db_engine, init_db, make_session_factory
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
from inkfish.tick.scheduler import run_simulation, run_tick
from inkfish.world.state import WorldState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEED_PATH = "data/seed/world.json"


def _make_action(
    character_id: str,
    tick_id: int,
    action_type: ActionType = ActionType.THINK,
    content: str = "pondering...",
    target: str | None = None,
    mood: str = "curious",
    inner_thought: str = "",
    triggers_interaction: bool = False,
) -> CharacterAction:
    """Build a valid CharacterAction for testing."""
    return CharacterAction(
        character_id=character_id,
        tick_id=tick_id,
        action_type=action_type,
        content=content,
        target=target,
        mood=mood,
        inner_thought=inner_thought,
        triggers_interaction=triggers_interaction,
    )


def _make_speak_action(
    character_id: str,
    tick_id: int,
    target: str = "char_zhao",
    mood: str = "cheerful",
) -> CharacterAction:
    return CharacterAction(
        character_id=character_id,
        tick_id=tick_id,
        action_type=ActionType.SPEAK,
        content="Hello there!",
        target=target,
        mood=mood,
        inner_thought="",
        triggers_interaction=True,
    )


def _patch_call_with_retry(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[tuple[str, int], CharacterAction] | None = None,
) -> list[dict[str, Any]]:
    """Monkeypatch ``call_with_retry`` to return scripted actions from *plan*.

    Any (character_id, tick_id) not in *plan* falls back to DO_NOTHING.
    Returns a list that is populated with call-kwargs on each invocation,
    so tests can assert on what was called.
    """
    calls: list[dict[str, Any]] = []
    if plan is None:
        plan = {}

    async def _fake_call_with_retry(
        client: Any,
        system: str,
        user: str,
        character_id: str,
        tick_id: int,
        *,
        on_log: Any,
        max_attempts: int = 3,
        base_temperature: float = 0.7,
        max_tokens: int = 16384,
        tool_schema: dict | None = None,
        allowed_targets: set[str] | None = None,
    ) -> CharacterAction:
        calls.append(
            dict(
                character_id=character_id,
                tick_id=tick_id,
                max_attempts=max_attempts,
                base_temperature=base_temperature,
                tool_schema_target_enum=(
                    tool_schema["properties"]["target"]["enum"]
                    if tool_schema else None
                ),
            )
        )
        key = (character_id, tick_id)
        return plan.get(key, fallback_do_nothing(character_id, tick_id))

    monkeypatch.setattr("inkfish.tick.scheduler.call_with_retry", _fake_call_with_retry)
    return calls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_bundle():  # type: ignore[return]
    """Return (repo, snapshots) backed by a fresh in-memory DB."""
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    sf = make_session_factory(engine)
    repo = Repository(sf)
    snapshots = SnapshotManager(sf)
    yield repo, snapshots
    engine.dispose()


@pytest.fixture
def seeded_world(repo_root: Any) -> WorldState:
    """Return a WorldState seeded from the canonical world.json (no DB)."""
    from inkfish.world.seed_loader import load_seed_file

    return load_seed_file(repo_root / _SEED_PATH)


@pytest.fixture
def dummy_client() -> Any:
    """Return a dummy object that stands in for DeepSeekClient (never called)."""

    class _DummyClient:
        model = "test-model"

    return _DummyClient()


# ---------------------------------------------------------------------------
# Tests: run_tick
# ---------------------------------------------------------------------------


async def test_run_tick_returns_one_action_per_character(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """run_tick must return exactly one action per character."""
    repo, snapshots = db_bundle
    # Persist tick-0 snapshot so load_world(0) works if needed
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)

    actions = await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    assert len(actions) == len(seeded_world.characters)


async def test_run_tick_persists_actions_to_db(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """Each action must be persisted as an ActionRow in the DB."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)

    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    rows = repo.get_actions_at_tick(1)
    assert len(rows) == len(seeded_world.characters)


async def test_run_tick_writes_snapshot_meta(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """SnapshotRow at tick_id=1 must have correct char_count and action_count."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)

    n_chars = len(seeded_world.characters)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    snap = repo.get_snapshot_meta(1)
    assert snap is not None
    assert snap.char_count == n_chars
    assert snap.action_count == n_chars  # one per character


async def test_run_tick_writes_character_rows_at_tick_id(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """CharacterRow WHERE tick_id=1 must return 5 rows."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    char_rows = repo.get_characters_at_tick(1)
    assert len(char_rows) == len(seeded_world.characters)


async def test_run_tick_writes_location_rows_at_tick_id(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """LocationRow WHERE tick_id=1 must return rows matching locations count."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    loc_rows = repo.get_locations_at_tick(1)
    assert len(loc_rows) == len(seeded_world.locations)


async def test_run_tick_advances_world_sim_time_and_tick_id(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """world.tick_id must equal tick_id and sim_time must advance by tick_interval_hours."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    initial_sim_time = seeded_world.sim_time
    interval = seeded_world.tick_interval_hours

    _patch_call_with_retry(monkeypatch)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    assert seeded_world.tick_id == 1
    assert seeded_world.sim_time == initial_sim_time + timedelta(hours=interval)


async def test_run_tick_updates_character_mood(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """Scripted action with mood='elated' → character's current_mood becomes 'elated'."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    target_char = seeded_world.characters[0]
    elated_action = _make_action(target_char.id, tick_id=1, mood="elated")
    plan = {(target_char.id, 1): elated_action}

    _patch_call_with_retry(monkeypatch, plan)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    updated_char = seeded_world.get_character(target_char.id)
    assert updated_char is not None
    assert updated_char.current_mood == "elated"


async def test_run_tick_applies_move_to_when_target_known(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """MOVE_TO with a known location id must update c.current_location."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    # Add a second location to the world so MOVE_TO has somewhere to go.
    from inkfish.world.state import Location

    second_loc = Location(
        id="loc_park",
        name="Park",
        description="A quiet park.",
        present_characters=[],
        connected_to=["loc_coffee_shop"],
    )
    seeded_world.locations.append(second_loc)

    target_char = seeded_world.characters[0]
    original_loc = target_char.current_location
    assert original_loc != "loc_park"  # sanity check

    move_action = CharacterAction(
        character_id=target_char.id,
        tick_id=1,
        action_type=ActionType.MOVE_TO,
        content="Heading to the park.",
        target="loc_park",
        mood="adventurous",
        inner_thought="",
        triggers_interaction=False,
    )
    plan = {(target_char.id, 1): move_action}

    _patch_call_with_retry(monkeypatch, plan)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    updated = seeded_world.get_character(target_char.id)
    assert updated is not None
    assert updated.current_location == "loc_park"


async def test_run_tick_ignores_move_to_unknown_target(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """MOVE_TO with an unknown target id must leave current_location unchanged."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    target_char = seeded_world.characters[0]
    original_loc = target_char.current_location

    move_action = CharacterAction(
        character_id=target_char.id,
        tick_id=1,
        action_type=ActionType.MOVE_TO,
        content="Trying to teleport.",
        target="loc_nowhere",
        mood="confused",
        inner_thought="",
        triggers_interaction=False,
    )
    plan = {(target_char.id, 1): move_action}

    _patch_call_with_retry(monkeypatch, plan)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    updated = seeded_world.get_character(target_char.id)
    assert updated is not None
    assert updated.current_location == original_loc


async def test_run_tick_increments_appearance_count_and_last_active_tick(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """After tick 1: appearance_count==1 and last_active_tick==1 for each char."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)
    await run_tick(1, seeded_world, dummy_client, repo, snapshots)

    for char in seeded_world.characters:
        assert char.appearance_count == 1, f"{char.id}: appearance_count should be 1"
        assert char.last_active_tick == 1, f"{char.id}: last_active_tick should be 1"


# ---------------------------------------------------------------------------
# Tests: run_simulation
# ---------------------------------------------------------------------------


async def test_run_simulation_runs_n_ticks(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """3 ticks × 5 chars = 15 total actions; 3 snapshots (plus tick-0 seed)."""
    repo, snapshots = db_bundle
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)

    _patch_call_with_retry(monkeypatch)
    n_chars = len(seeded_world.characters)

    actions = await run_simulation(
        3,
        world=seeded_world,
        client=dummy_client,
        repo=repo,
        snapshots=snapshots,
        start_tick=0,
    )

    assert len(actions) == 3 * n_chars

    # 3 new snapshots (tick 1, 2, 3) plus the seed snapshot (tick 0)
    all_snaps = snapshots.list_snapshots()
    assert len(all_snaps) == 4  # tick 0 (seed) + tick 1, 2, 3


async def test_run_simulation_with_start_tick_resumes(
    monkeypatch: pytest.MonkeyPatch,
    db_bundle: Any,
    seeded_world: WorldState,
    dummy_client: Any,
) -> None:
    """start_tick=2, n_ticks=3 → ticks 3, 4, 5 are produced."""
    repo, snapshots = db_bundle

    # Seed snapshots for ticks 0, 1, 2 so load_world works.
    snapshots.save_snapshot(seeded_world, tick_id=0, action_count=0)
    # Simulate ticks 1 and 2 already done
    seeded_world.tick_id = 2
    snapshots.save_snapshot(seeded_world, tick_id=2, action_count=0)

    _patch_call_with_retry(monkeypatch)

    actions = await run_simulation(
        3,
        world=seeded_world,
        client=dummy_client,
        repo=repo,
        snapshots=snapshots,
        start_tick=2,
    )

    # Should produce ticks 3, 4, 5
    n_chars = len(seeded_world.characters)
    assert len(actions) == 3 * n_chars

    # All actions should have tick_id in {3, 4, 5}
    tick_ids_produced = {a.tick_id for a in actions}
    assert tick_ids_produced == {3, 4, 5}

    # World should end at tick_id == 5
    assert seeded_world.tick_id == 5
