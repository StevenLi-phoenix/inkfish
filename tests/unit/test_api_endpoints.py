"""Unit tests for inkfish.api — 5 routers / 9 endpoints.

All LLM calls are blocked by monkeypatching ``call_with_retry`` in the scheduler.
The TestClient uses FastAPI's dependency_overrides to inject in-memory DB instances.
Tests use a shared ``api_client`` fixture that:
  1. Sets INKFISH_DB_URL to a tmp file DB
  2. Busts the lru_cache on deps to force re-initialisation with the new env var
  3. Returns a synchronous FastAPI TestClient
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.character.validator import fallback_do_nothing
from inkfish.storage.db import create_db_engine, init_db, make_session_factory
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
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
    mood: str = "curious",
) -> CharacterAction:
    return CharacterAction(
        character_id=character_id,
        tick_id=tick_id,
        action_type=action_type,
        content=content,
        target=None,
        mood=mood,
        inner_thought="test thought",
        triggers_interaction=False,
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch call_with_retry in the scheduler to return DO_NOTHING actions."""

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
        return fallback_do_nothing(character_id, tick_id)

    monkeypatch.setattr("inkfish.tick.scheduler.call_with_retry", _fake_call_with_retry)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_bundle(tmp_path: Path):  # type: ignore[return]
    """Return (repo, snapshots, db_url) backed by a tmp file SQLite DB."""
    db_file = tmp_path / "api_test.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_db_engine(db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    repo = Repository(sf)
    snaps = SnapshotManager(sf)
    yield repo, snaps, db_url
    engine.dispose()


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[return]
    """Return a FastAPI TestClient with an isolated tmp-file DB.

    Sets INKFISH_DB_URL + DEEPSEEK_API_KEY env vars and busts all lru_caches
    so each test gets a fresh DB connection pool.
    """
    db_file = tmp_path / "api_client_test.db"
    db_url = f"sqlite:///{db_file}"

    monkeypatch.setenv("INKFISH_DB_URL", db_url)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-fake-key-1234567890")

    # Bust lru_caches so the new env vars take effect
    from inkfish.api.deps import _engine_and_factory, get_settings, get_sim_config

    _engine_and_factory.cache_clear()
    get_settings.cache_clear()
    get_sim_config.cache_clear()

    from inkfish.api.main import app

    with TestClient(app) as client:
        yield client

    # Ensure caches are cleared after test too
    _engine_and_factory.cache_clear()
    get_settings.cache_clear()
    get_sim_config.cache_clear()


@pytest.fixture
def seeded_world(repo_root: Path) -> WorldState:
    """Return a WorldState loaded from the canonical seed file."""
    from inkfish.world.seed_loader import load_seed_file

    return load_seed_file(repo_root / _SEED_PATH)


@pytest.fixture
def seeded_client(
    api_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_root: Path
):  # type: ignore[return]
    """Return a TestClient backed by a seeded DB (tick 0 written).

    Seeds the DB in-process using seed_loader + SnapshotManager so we don't
    depend on the CLI.  The client's INKFISH_DB_URL fixture is already set.
    """
    # Retrieve the db_url that api_client fixture already set
    import os

    db_url = os.environ["INKFISH_DB_URL"]
    engine = create_db_engine(db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    snaps = SnapshotManager(sf)

    from inkfish.world.seed_loader import load_seed_file

    world = load_seed_file(repo_root / _SEED_PATH)
    snaps.save_snapshot(world, tick_id=0, action_count=0)
    engine.dispose()

    yield api_client, world


# ---------------------------------------------------------------------------
# 1. GET /health — no seed
# ---------------------------------------------------------------------------


def test_health_ok_no_seed(api_client: TestClient) -> None:
    """GET /health returns 200 with latest_tick=None when DB is empty."""
    resp = api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["phase"] == "P0"
    assert data["latest_tick"] is None
    assert data["sim_running"] is False


# ---------------------------------------------------------------------------
# 2. GET /health — after seed
# ---------------------------------------------------------------------------


def test_health_after_seed(seeded_client: Any) -> None:
    """GET /health returns latest_tick=0 after seeding."""
    client, _ = seeded_client
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["latest_tick"] == 0


# ---------------------------------------------------------------------------
# 3. POST /simulation/start — 400 when no seed
# ---------------------------------------------------------------------------


def test_simulation_start_400_when_no_seed(api_client: TestClient) -> None:
    """POST /simulation/start returns 400 when the DB has no snapshots."""
    resp = api_client.post("/simulation/start", json={"n_ticks": 1})
    assert resp.status_code == 400
    assert "snapshot" in resp.json()["detail"].lower() or "seed" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. POST /simulation/start — runs n_ticks
# ---------------------------------------------------------------------------


def test_simulation_start_runs_n_ticks(seeded_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /simulation/start n_ticks=2 produces 10 ActionRows and 3 SnapshotRows."""
    client, world = seeded_client
    _patch_llm(monkeypatch)

    resp = client.post("/simulation/start", json={"n_ticks": 2})
    assert resp.status_code == 202, resp.json()
    data = resp.json()
    assert data["n_ticks"] == 2
    assert data["from_tick"] == 0
    assert "task_id" in data

    # Verify via /snapshot that 3 snapshots exist (tick 0, 1, 2)
    snap_resp = client.get("/snapshot")
    assert snap_resp.status_code == 200
    snaps = snap_resp.json()["snapshots"]
    assert len(snaps) == 3  # tick 0 (seed) + tick 1 + tick 2

    # Verify /tick/2 has 5 actions
    tick_resp = client.get("/tick/2")
    assert tick_resp.status_code == 200
    tick_data = tick_resp.json()
    assert tick_data["tick_id"] == 2
    # 5 characters → 5 actions per tick
    assert tick_data["action_count"] == len(world.characters)
    assert len(tick_data["actions"]) == len(world.characters)


# ---------------------------------------------------------------------------
# 5. POST /simulation/pause — noop
# ---------------------------------------------------------------------------


def test_simulation_pause_returns_noop(api_client: TestClient) -> None:
    """POST /simulation/pause returns 200 with status=noop."""
    resp = api_client.post("/simulation/pause", json={"reason": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "noop"
    assert data["phase"] == "P0"


# ---------------------------------------------------------------------------
# 6. POST /simulation/reset — deletes ticks > N
# ---------------------------------------------------------------------------


def test_simulation_reset_deletes_data(seeded_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """After running 3 ticks, reset to tick=0 leaves only tick 0 snapshot."""
    client, _ = seeded_client
    _patch_llm(monkeypatch)

    # Run 3 ticks
    run_resp = client.post("/simulation/start", json={"n_ticks": 3})
    assert run_resp.status_code == 202

    # Verify we have 4 snapshots (0, 1, 2, 3)
    pre = client.get("/snapshot").json()["snapshots"]
    assert len(pre) == 4

    # Reset to tick 0
    reset_resp = client.post("/simulation/reset", json={"tick_id": 0})
    assert reset_resp.status_code == 200
    assert reset_resp.json()["reset_to_tick"] == 0

    # Now only tick 0 remains
    post = client.get("/snapshot").json()["snapshots"]
    assert len(post) == 1
    assert post[0]["tick_id"] == 0


# ---------------------------------------------------------------------------
# 7. GET /tick — latest tick state
# ---------------------------------------------------------------------------


def test_tick_latest_returns_tick_state(
    seeded_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /tick returns the latest tick after simulating 1 tick."""
    client, world = seeded_client
    _patch_llm(monkeypatch)

    run_resp = client.post("/simulation/start", json={"n_ticks": 1})
    assert run_resp.status_code == 202

    resp = client.get("/tick")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tick_id"] == 1
    assert data["action_count"] == len(world.characters)
    assert len(data["actions"]) == len(world.characters)


# ---------------------------------------------------------------------------
# 8. GET /tick/{tick_id} — tick 0 has 0 actions
# ---------------------------------------------------------------------------


def test_tick_by_id(seeded_client: Any) -> None:
    """GET /tick/0 returns tick=0 with 0 actions (seed tick)."""
    client, _ = seeded_client
    resp = client.get("/tick/0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tick_id"] == 0
    assert data["action_count"] == 0
    assert data["actions"] == []


# ---------------------------------------------------------------------------
# 9. GET /tick/{tick_id} — 404 for nonexistent tick
# ---------------------------------------------------------------------------


def test_tick_404_when_not_exist(api_client: TestClient) -> None:
    """GET /tick/999 returns 404 when tick 999 does not exist."""
    resp = api_client.get("/tick/999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. GET /snapshot — list after seed
# ---------------------------------------------------------------------------


def test_snapshot_list_after_seed(seeded_client: Any) -> None:
    """GET /snapshot returns exactly 1 snapshot (tick 0) after seeding."""
    client, _ = seeded_client
    resp = client.get("/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "snapshots" in data
    assert len(data["snapshots"]) == 1
    assert data["snapshots"][0]["tick_id"] == 0


# ---------------------------------------------------------------------------
# 11. GET /character — 5 characters after seed
# ---------------------------------------------------------------------------


def test_character_list_returns_5(seeded_client: Any) -> None:
    """GET /character returns 5 characters after seeding."""
    client, world = seeded_client
    resp = client.get("/character")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tick_id"] == 0
    assert len(data["characters"]) == len(world.characters)
    # All expected character IDs should be present
    ids = {c["id"] for c in data["characters"]}
    expected_ids = {c.id for c in world.characters}
    assert ids == expected_ids


# ---------------------------------------------------------------------------
# 12. GET /character/{id} — detail with recent_actions
# ---------------------------------------------------------------------------


def test_character_detail_returns_with_recent_actions(
    seeded_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /character/{id} returns background and non-empty recent_actions after 1 tick."""
    client, world = seeded_client
    _patch_llm(monkeypatch)

    # Run 1 tick so the character has actions
    run_resp = client.post("/simulation/start", json={"n_ticks": 1})
    assert run_resp.status_code == 202

    char_id = world.characters[0].id
    resp = client.get(f"/character/{char_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["character"]["id"] == char_id
    assert isinstance(data["background"], str) and len(data["background"]) > 0
    assert isinstance(data["appearance"], str)
    assert isinstance(data["personality"], str)
    assert isinstance(data["routine"], dict)
    assert len(data["recent_actions"]) > 0
    assert data["recent_actions"][0]["character_id"] == char_id


# ---------------------------------------------------------------------------
# 13. GET /character/{id} — 404 for unknown character
# ---------------------------------------------------------------------------


def test_character_detail_404_for_unknown(seeded_client: Any) -> None:
    """GET /character/char_unknown returns 404."""
    client, _ = seeded_client
    resp = client.get("/character/char_unknown_xyzzy")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 14. GET /openapi.json — all 9 endpoints present
# ---------------------------------------------------------------------------


def test_openapi_schema_has_all_endpoints(api_client: TestClient) -> None:
    """GET /openapi.json contains all 9 expected endpoint paths."""
    resp = api_client.get("/openapi.json")
    assert resp.status_code == 200
    paths = set(resp.json()["paths"].keys())

    required = {
        "/health",
        "/simulation/start",
        "/simulation/pause",
        "/simulation/reset",
        "/tick",
        "/tick/{tick_id}",
        "/snapshot",
        "/character",
        "/character/{character_id}",
    }
    missing = required - paths
    assert not missing, f"Missing OpenAPI paths: {missing}"
