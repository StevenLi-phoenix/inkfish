"""Unit tests for inkfish.character.context — prompt builder.

Covers:
- byte-stability of block [1] (persona) across repeated calls
- byte-stability of block [2] (memory stub) in P0
- block [3] (perception) changes with tick_id / sim_time
- self-exclusion from 'others' list in perception
- full prompt structure and DeepSeek JSON-mode requirement
- golden snapshot for char_lin's persona block
- cache threshold: persona blocks ≥ 700 chars each
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from inkfish.character.context import (
    build_memory_block,
    build_perception_block,
    build_persona_block,
    build_user_prompt,
    load_system_prompt,
)
from inkfish.world.state import WorldState

# ---------------------------------------------------------------------------
# Golden snapshot helper
# ---------------------------------------------------------------------------


def _check_or_write_golden(content: str, name: str) -> None:
    golden_dir = Path(__file__).parent / "__golden__"
    golden_dir.mkdir(exist_ok=True)
    golden_path = golden_dir / f"{name}.txt"
    if not golden_path.exists():
        golden_path.write_text(content, encoding="utf-8")
        pytest.skip(f"Created golden file: {golden_path}")
    expected = golden_path.read_text(encoding="utf-8")
    assert content == expected, f"Golden mismatch for {name}"


# ---------------------------------------------------------------------------
# Block [1] — persona stability
# ---------------------------------------------------------------------------


def test_persona_block_byte_stable_across_calls(seed_world_state: WorldState) -> None:
    """Block [1] is byte-identical across 5 sequential calls — cache invariant."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None

    first = build_persona_block(char)
    for _ in range(4):
        assert build_persona_block(char) == first, (
            "build_persona_block returned different output on repeated call"
        )


def test_persona_blocks_unique_per_character(seed_world_state: WorldState) -> None:
    """5 characters yield 5 distinct persona block strings."""
    blocks = [build_persona_block(c) for c in seed_world_state.characters]
    assert len(set(blocks)) == len(blocks), "Two characters produced identical persona blocks"


def test_persona_block_no_dynamic_fields(seed_world_state: WorldState) -> None:
    """Persona block must NOT contain tick_id, sim_time, mood, or location id.

    These are perception-only — including them in block [1] would break cache.
    """
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    block = build_persona_block(char)

    # tick_id patterns — look for literal "tick" followed by a digit
    import re

    assert not re.search(r"tick\s*\d", block), "Persona block contains tick reference"

    # current_mood should not appear verbatim in persona block
    assert char.current_mood not in block, (
        "Persona block contains current_mood — it should only appear in perception block"
    )

    # current_location id should not appear verbatim in persona block
    assert char.current_location not in block, (
        "Persona block contains current_location id — it should only appear in perception block"
    )


def test_persona_block_size_meets_cache_threshold(seed_world_state: WorldState) -> None:
    """Each of the 5 characters' persona blocks must be ≥ 700 chars.

    DeepSeek cache threshold is ~1024 tokens; Chinese text at ~1.5 token/char
    means 700 chars ≈ 1050 tokens — just above the threshold.
    """
    for char in seed_world_state.characters:
        block = build_persona_block(char)
        assert len(block) >= 700, (
            f"Persona block for {char.id} is only {len(block)} chars "
            f"(need ≥ 700 for DeepSeek cache threshold)"
        )


def test_routine_key_order_deterministic(seed_world_state: WorldState) -> None:
    """Routine keys are sorted alphabetically — multiple calls produce the same order."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None

    block_a = build_persona_block(char)
    block_b = build_persona_block(char)
    assert block_a == block_b

    # Verify keys are truly sorted by extracting the key portion
    routine_keys_in_block = [
        line.strip().split("：")[0]
        for line in block_a.splitlines()
        if line.startswith("    ") and "：" in line
    ]
    assert routine_keys_in_block == sorted(routine_keys_in_block), (
        f"Routine keys are not sorted: {routine_keys_in_block}"
    )


# ---------------------------------------------------------------------------
# Block [2] — memory stub stability
# ---------------------------------------------------------------------------


def test_memory_block_byte_stable_in_p0(seed_world_state: WorldState) -> None:
    """Block [2] is byte-identical (literal constant) for all characters."""
    results = [
        build_memory_block(char, seed_world_state)
        for char in seed_world_state.characters
    ]
    assert len(set(results)) == 1, "Memory block differs between characters"

    # Also verify calling twice for same character is identical
    char = seed_world_state.characters[0]
    assert build_memory_block(char, seed_world_state) == build_memory_block(
        char, seed_world_state
    )


# ---------------------------------------------------------------------------
# Block [3] — perception variability
# ---------------------------------------------------------------------------


def test_perception_block_changes_with_tick(seed_world_state: WorldState) -> None:
    """Block [3] varies when tick_id changes."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    block_tick0 = build_perception_block(char, seed_world_state, 0, sim_time)
    block_tick1 = build_perception_block(char, seed_world_state, 1, sim_time)
    assert block_tick0 != block_tick1, (
        "Perception block did not change when tick_id changed"
    )


def test_perception_block_changes_with_sim_time(seed_world_state: WorldState) -> None:
    """Block [3] varies when sim_time changes."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None

    t1 = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)

    block_t1 = build_perception_block(char, seed_world_state, 0, t1)
    block_t2 = build_perception_block(char, seed_world_state, 0, t2)
    assert block_t1 != block_t2, "Perception block did not change when sim_time changed"


def test_perception_block_omits_self_from_others_list(
    seed_world_state: WorldState,
) -> None:
    """When building char_lin's perception, char_lin must NOT appear in 在场其他人."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    block = build_perception_block(char, seed_world_state, 0, sim_time)

    # The others section should not contain char_lin's own name or ID
    others_section_start = block.find("在场其他人")
    assert others_section_start != -1, "Perception block missing 在场其他人 section"

    others_section = block[others_section_start:]
    assert char.name not in others_section, (
        f"Character's own name ({char.name}) appeared in 在场其他人"
    )
    assert char.id not in others_section, (
        f"Character's own id ({char.id}) appeared in 在场其他人"
    )


def test_perception_block_contains_location_info(seed_world_state: WorldState) -> None:
    """Perception block contains the location name."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    block = build_perception_block(char, seed_world_state, 0, sim_time)
    location = seed_world_state.get_location(char.current_location)
    assert location is not None
    assert location.name in block, "Perception block missing location name"


def test_perception_block_contains_mood(seed_world_state: WorldState) -> None:
    """Perception block contains the character's current mood."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    block = build_perception_block(char, seed_world_state, 0, sim_time)
    assert char.current_mood in block, "Perception block missing current_mood"


# ---------------------------------------------------------------------------
# Full prompt
# ---------------------------------------------------------------------------


def test_full_prompt_contains_all_three_blocks(seed_world_state: WorldState) -> None:
    """Final user prompt contains the literal labels 人设, 记忆, 当前感知."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    prompt = build_user_prompt(char, seed_world_state, 0, sim_time)
    assert "人设：" in prompt, "User prompt missing 人设 block label"
    assert "记忆：" in prompt, "User prompt missing 记忆 block label"
    assert "当前感知：" in prompt, "User prompt missing 当前感知 block label"


def test_full_prompt_includes_word_json(seed_world_state: WorldState) -> None:
    """DeepSeek JSON-mode requirement: the literal 'json' must appear in user prompt."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    prompt = build_user_prompt(char, seed_world_state, 0, sim_time)
    assert "json" in prompt, (
        "User prompt must contain the literal word 'json' for DeepSeek JSON mode"
    )


def test_full_prompt_ends_with_json_instruction(seed_world_state: WorldState) -> None:
    """Full user prompt ends with the JSON output instruction."""
    char = seed_world_state.get_character("char_lin")
    assert char is not None
    sim_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    prompt = build_user_prompt(char, seed_world_state, 0, sim_time)
    assert prompt.rstrip().endswith("请以 json 对象输出本回合的 action。"), (
        "User prompt does not end with JSON output instruction"
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


def test_load_system_prompt_returns_nonempty_with_word_json() -> None:
    """System prompt file exists and contains 'json'."""
    prompt = load_system_prompt()
    assert len(prompt) > 0, "System prompt is empty"
    assert "json" in prompt, "System prompt must contain 'json' for DeepSeek JSON mode"


def test_load_system_prompt_cached() -> None:
    """Calling load_system_prompt() twice returns the same object (cached)."""
    first = load_system_prompt()
    second = load_system_prompt()
    assert first is second, "load_system_prompt() is not caching the result"


def test_system_prompt_no_character_specific_data() -> None:
    """System prompt must not contain character-specific data (would break cache)."""
    prompt = load_system_prompt()
    # Check that no character IDs or names from seed world appear in system prompt
    character_ids = ["char_lin", "char_zhao", "char_chen", "char_wang", "char_li"]
    for cid in character_ids:
        assert cid not in prompt, (
            f"System prompt contains character id {cid!r} — "
            "character-specific data breaks prompt cache"
        )


# ---------------------------------------------------------------------------
# Golden snapshot
# ---------------------------------------------------------------------------


def test_persona_block_golden_lin(seed_world_state: WorldState) -> None:
    """char_lin's persona block matches the golden file byte-for-byte.

    On first run (no golden file), writes the current output and skips.
    Subsequent runs assert match.
    """
    char = seed_world_state.get_character("char_lin")
    assert char is not None

    block = build_persona_block(char)
    _check_or_write_golden(block, "persona_char_lin")
