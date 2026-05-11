"""P0 D11 killer test — verifies reset() correctness against real LLM.

Workflow:
1. Fresh seed → run 10 ticks = set A (actions for ticks 6-10)
2. Reset to tick 5 → run 5 more ticks = set B (actions for ticks 6-10)
3. Assert:
   - 25 actions in set A and set B
   - All set B actions pass Pydantic CharacterAction validation
   - A vs B content differs on ≥60% of (character, tick) pairs (LLM nondeterminism)
   - Soft personality consistency check (logged, not hard-asserted)

Isolated DB at data/inkfish_killer.db via INKFISH_DB_URL — does NOT touch the
main inkfish.db that D10 produced.

Default-live: no env gate. Expected runtime ~30 min (~$0.02 LLM cost).
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import select

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.storage.db import create_db_engine, make_session_factory
from inkfish.storage.models import ActionRow

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "inkfish_killer.db"


def _cli(*args: str) -> None:
    """Run the inkfish CLI against the isolated killer DB."""
    env = {**os.environ, "INKFISH_DB_URL": f"sqlite:///{DB_PATH}"}
    subprocess.run(
        ["uv", "run", "inkfish", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


def _get_actions(tick_lo: int, tick_hi: int) -> list[ActionRow]:
    engine = create_db_engine(f"sqlite:///{DB_PATH}")
    sf = make_session_factory(engine)
    with sf() as s:
        rows = (
            s.execute(
                select(ActionRow).where(
                    ActionRow.tick_id >= tick_lo,
                    ActionRow.tick_id <= tick_hi,
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


@pytest.mark.live
def test_killer_reset_end_to_end() -> None:
    """End-to-end killer test — see module docstring."""
    # ─── Wipe isolated DB for a clean baseline ───────────────────────────────
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH.with_name(DB_PATH.name + suffix)
        if p.exists():
            p.unlink()

    # ─── Phase 1: Fresh seed + 10-tick run → set A ───────────────────────────
    _cli("seed")
    _cli("run", "--ticks", "10")
    set_a = _get_actions(6, 10)
    assert len(set_a) == 25, f"Set A: expected 25 actions, got {len(set_a)}"

    # ─── Phase 2: Reset to tick 5 + 5-tick re-run → set B ────────────────────
    _cli("reset", "5")
    _cli("run", "--from-tick", "5", "--ticks", "5")
    set_b = _get_actions(6, 10)
    assert len(set_b) == 25, f"Set B: expected 25 actions, got {len(set_b)}"

    # ─── Assertion 1: All B actions pass Pydantic validation ─────────────────
    for a in set_b:
        CharacterAction(
            character_id=a.character_id,
            tick_id=a.tick_id,
            action_type=ActionType(a.action_type),
            content=a.content,
            target=a.target,
            mood=a.mood,
            inner_thought=a.inner_thought,
            triggers_interaction=a.triggers_interaction,
        )

    # ─── Assertion 2: A vs B content differs (LLM nondeterminism) ────────────
    by_key_a = {(a.character_id, a.tick_id): a.content for a in set_a}
    by_key_b = {(a.character_id, a.tick_id): a.content for a in set_b}
    common = set(by_key_a) & set(by_key_b)
    different = sum(1 for k in common if by_key_a[k] != by_key_b[k])
    diff_pct = different / len(common) if common else 0.0
    print(f"\nContent differs in {different}/{len(common)} pairs ({100 * diff_pct:.1f}%)")
    assert diff_pct >= 0.6, (
        f"Expected ≥60% content differences, got {100 * diff_pct:.1f}% — "
        "LLM may be deterministic at temp=0.7 or content is identical for some reason."
    )

    # ─── Soft check: per-character action distribution (logged only) ─────────
    by_char_b: dict[str, Counter[str]] = {
        c: Counter() for c in {"char_lin", "char_zhao", "char_chen", "char_wang", "char_li"}
    }
    for a in set_b:
        if a.character_id in by_char_b:
            by_char_b[a.character_id][a.action_type] += 1
    print("\nSet B action distribution by character (ticks 6-10):")
    for cid, dist in by_char_b.items():
        print(f"  {cid}: {dict(dist)}")
