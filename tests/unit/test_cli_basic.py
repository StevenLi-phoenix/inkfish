"""Basic unit tests for the INKFISH CLI (inkfish.cli).

Uses typer.testing.CliRunner — no real DB or LLM calls in these tests.
DB-touching tests inject INKFISH_DB_URL via environment to point at a
pytest-managed temp directory file, isolating from the real inkfish.db.

Tests:
1. version  — outputs "inkfish 0.1.0 (P0)"
2. seed     — exit code 0, "Seeded world" in output
3. list-snapshots after seed — shows 1 snapshot at tick 0
4. reset after seed — exit code 0, "Reset to tick 0" in output
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from inkfish.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_path(repo_root: Path) -> str:
    return str(repo_root / "data" / "seed" / "world.json")


# ---------------------------------------------------------------------------
# Test 1 — version
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    """inkfish version must output 'inkfish 0.1.0 (P0)'."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert "inkfish 0.1.0 (P0)" in result.output


# ---------------------------------------------------------------------------
# Test 2 — seed
# ---------------------------------------------------------------------------


def test_cli_seed_creates_db_and_loads_world(
    tmp_path: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """inkfish seed must exit 0 and print 'Seeded world'."""
    db_file = tmp_path / "test_cli.db"
    db_url = f"sqlite:///{db_file}"

    monkeypatch.setenv("INKFISH_DB_URL", db_url)

    result = runner.invoke(
        app,
        ["seed", "--seed-path", _seed_path(repo_root)],
        env={"INKFISH_DB_URL": db_url},
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"Non-zero exit:\n{result.output}"
    assert "Seeded world" in result.output
    assert "chars=5" in result.output
    assert "locs=1" in result.output


# ---------------------------------------------------------------------------
# Test 3 — list-snapshots after seed
# ---------------------------------------------------------------------------


def test_cli_list_snapshots_after_seed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """After seed, list-snapshots must show exactly 1 snapshot at tick 0."""
    db_file = tmp_path / "test_cli_list.db"
    db_url = f"sqlite:///{db_file}"
    env = {"INKFISH_DB_URL": db_url}

    # Seed first
    seed_result = runner.invoke(
        app,
        ["seed", "--seed-path", _seed_path(repo_root)],
        env=env,
        catch_exceptions=False,
    )
    assert seed_result.exit_code == 0, seed_result.output

    # Then list
    list_result = runner.invoke(
        app,
        ["list-snapshots"],
        env=env,
        catch_exceptions=False,
    )
    assert list_result.exit_code == 0, list_result.output
    # Should show a header row + exactly one data row for tick 0
    lines = [line.strip() for line in list_result.output.splitlines() if line.strip()]
    # Find the tick-0 line
    tick_0_lines = [line for line in lines if line.startswith("0 ")]
    assert len(tick_0_lines) == 1, (
        f"Expected exactly one tick-0 snapshot line, got: {list_result.output!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — reset after seed
# ---------------------------------------------------------------------------


def test_cli_reset_after_seed(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """inkfish reset 0 after seed must exit 0 and print 'Reset to tick 0'."""
    db_file = tmp_path / "test_cli_reset.db"
    db_url = f"sqlite:///{db_file}"
    env = {"INKFISH_DB_URL": db_url}

    # Seed first
    seed_result = runner.invoke(
        app,
        ["seed", "--seed-path", _seed_path(repo_root)],
        env=env,
        catch_exceptions=False,
    )
    assert seed_result.exit_code == 0, seed_result.output

    # Then reset
    reset_result = runner.invoke(
        app,
        ["reset", "0"],
        env=env,
        catch_exceptions=False,
    )
    assert reset_result.exit_code == 0, reset_result.output
    assert "Reset to tick 0" in reset_result.output
