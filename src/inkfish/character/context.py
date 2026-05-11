"""inkfish.character.context — Prompt builder for character LLM calls.

Assembles three blocks:
  [1] Persona  — cache-stable, byte-identical across ticks for the same character
  [2] Memory   — P0 stub, also cache-stable (literal constant string)
  [3] Perception — per-tick, changes with tick_id / sim_time / world state

DeepSeek automatic prefix caching fires when the prefix (system + [1] + [2])
is ≥ 1024 tokens.  The persona block for each of the 5 seed characters is
≈ 750–900 characters of Chinese text (≈ 1125–1350 tokens), comfortably above
the threshold.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inkfish.world.state import Character, Location, WorldState

# ---------------------------------------------------------------------------
# System prompt — loaded once, cached
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_PATH: Path = (
    Path(__file__).parent.parent.parent.parent / "prompts" / "character_system.txt"
)
_SYSTEM_PROMPT_CACHE: str | None = None

_WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]

# P0 stub — must remain a literal constant so block [2] is byte-stable.
_MEMORY_STUB = "记忆：（暂无记录的过往事件或关系。P1 将启用记忆系统。）"


def load_system_prompt(path: Path = _SYSTEM_PROMPT_PATH) -> str:
    """Return the contents of prompts/character_system.txt.

    The result is cached at module level after the first call so that the file
    is read only once per process.
    """
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        _SYSTEM_PROMPT_CACHE = path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT_CACHE


def build_persona_block(character: Character) -> str:
    """Return the cache-stable [1] persona block for *character*.

    Uses ONLY stable fields: id, name, age, mbti, personality, background,
    routine.  Deliberately excludes tick_id, sim_time, current_mood, and
    current_location — those belong to block [3].

    The output is byte-identical for the same character across ticks.
    Routine keys are sorted alphabetically to eliminate dict-ordering
    nondeterminism.
    """
    routine_lines = "\n".join(f"    {k}：{v}" for k, v in sorted(character.routine.items()))
    return (
        f"人设：\n"
        f"  ID：{character.id}\n"
        f"  姓名：{character.name}\n"
        f"  年龄：{character.age}\n"
        f"  MBTI：{character.mbti}\n"
        f"  性格：{character.personality}\n"
        f"  背景：{character.background}\n"
        f"  日常作息：\n"
        f"{routine_lines}"
    )


def build_memory_block(character: Character, world: WorldState) -> str:  # noqa: ARG001
    """Return the cache-stable [2] memory block.

    P0: returns a fixed stub string.  No dynamic data is included so block [2]
    is byte-identical across all ticks and all characters.
    """
    return _MEMORY_STUB


def _format_sim_time(sim_time: datetime) -> str:
    """Format a datetime as '2026年01月15日 周四 上午8点'."""
    weekday_cn = _WEEKDAY_CN[sim_time.weekday()]
    hour = sim_time.hour
    if hour < 12:
        period = "上午"
        display_hour = hour if hour > 0 else 12
    elif hour < 13:
        period = "中午"
        display_hour = 12
    else:
        period = "下午"
        display_hour = hour - 12 if hour > 12 else 12
    return (
        f"{sim_time.year}年{sim_time.month:02d}月{sim_time.day:02d}日 "
        f"周{weekday_cn} {period}{display_hour}点"
    )


def build_perception_block(
    character: Character,
    world: WorldState,
    tick_id: int,
    sim_time: datetime,
) -> str:
    """Return the per-tick [3] perception block for *character*.

    This block changes with tick_id / sim_time / world state.  It must NOT
    include character.current_mood from block [1] — it is included here as a
    dynamic field that may change each tick.

    P0: 'previous-tick visible actions' for other characters are omitted (no
    action history is threaded through yet).  P1 will add this.
    """
    location: Location | None = world.get_location(character.current_location)
    loc_name = location.name if location else character.current_location
    loc_desc = location.description if location else ""

    others_at_loc = [
        c for c in world.characters_at_location(character.current_location) if c.id != character.id
    ]

    if others_at_loc:
        others_lines = "\n".join(
            f"    - [id={c.id}] {c.name}（{c.mbti}, {c.age}岁）：外貌 {c.appearance}"
            for c in others_at_loc
        )
        others_section = (
            "  在场其他人（target 必须用 [id=...] 中的字符串，不要用姓名或自创变体）：\n"
            f"{others_lines}"
        )
    else:
        others_section = "  在场其他人：（无）"

    return (
        f"当前感知：\n"
        f"  时间：{_format_sim_time(sim_time)}\n"
        f"  回合：tick {tick_id}\n"
        f"  地点：{loc_name} — {loc_desc}\n"
        f"{others_section}\n"
        f"  你当前的心情：{character.current_mood}"
    )


def build_user_prompt(
    character: Character,
    world: WorldState,
    tick_id: int,
    sim_time: datetime,
) -> str:
    """Stitch blocks [1] + [2] + [3] into the full user-turn prompt.

    The final line is the JSON instruction that satisfies DeepSeek's
    ``response_format={"type": "json_object"}`` requirement.
    """
    persona = build_persona_block(character)
    memory = build_memory_block(character, world)
    perception = build_perception_block(character, world, tick_id, sim_time)
    return (
        f"{persona}\n\n" f"{memory}\n\n" f"{perception}\n\n" "请以 json 对象输出本回合的 action。"
    )
