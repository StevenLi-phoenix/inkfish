"""inkfish.tick.scheduler — P0 sequential tick loop.

The scheduler is deliberately single-threaded in P0 for debuggability and
determinism.  P2 will introduce asyncio.gather for concurrent character calls.

Key invariants:
- ``run_tick`` NEVER raises on per-character LLM failure.  ``call_with_retry``
  guarantees a ``DO_NOTHING`` fallback, so the loop always produces exactly
  one action per character.
- Character in-memory state is mutated sequentially.  Later characters in the
  same tick therefore "see" the state left by earlier ones (mood, location).
  This is a P0-acceptable approximation; P1 will snapshot perceptions before
  any mutations.
- Every LLM call is logged via ``on_log=repo.log_llm`` before any parsing
  occurs — raw API data is durable even if the process crashes mid-tick.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from inkfish.character.context import build_user_prompt, load_system_prompt
from inkfish.character.schema import ActionType, CharacterAction
from inkfish.llm import DeepSeekClient, call_with_retry
from inkfish.storage.models import ActionRow
from inkfish.storage.repository import Repository
from inkfish.storage.snapshot import SnapshotManager
from inkfish.world.state import WorldState

if TYPE_CHECKING:
    from inkfish.config import SimConfig

logger = logging.getLogger(__name__)


_ACTION_TYPES = ["SPEAK", "THINK", "ACT", "MOVE_TO", "REACT", "DO_NOTHING"]


def _build_action_tool_schema(char: "Character", world: WorldState) -> dict:
    """Build per-character JSON Schema for the ``submit_action`` tool.

    Constraints encoded by the schema (enforced server-side by DeepSeek):
    - ``action_type`` ∈ 6 fixed values
    - ``target`` ∈ {char_id of others present at same location} ∪
                   {known location ids} ∪ {""} (empty string = None)
    - ``content`` ≤ 500 chars (prevents v4-pro reasoning + content overflow)
    - ``inner_thought`` ≤ 500 chars
    - ``mood`` ≤ 100 chars

    The empty-string sentinel for ``target`` exists because OpenAI strict mode
    historically rejects mixed ``["string", "null"]`` types in tool schemas.
    The retry / validator layer maps "" back to ``None``.
    """
    present_char_ids = [
        c.id for c in world.characters
        if c.current_location == char.current_location and c.id != char.id and c.alive
    ]
    known_loc_ids = [loc.id for loc in world.locations]
    target_enum = sorted(set(present_char_ids + known_loc_ids)) + [""]

    return {
        "type": "object",
        "properties": {
            "action_type": {"type": "string", "enum": _ACTION_TYPES},
            "content": {"type": "string", "maxLength": 500},
            "target": {
                "type": "string",
                "enum": target_enum,
                "description": "character_id or location_id; empty string for none.",
            },
            "mood": {"type": "string", "maxLength": 100},
            "inner_thought": {"type": "string", "maxLength": 500},
            "triggers_interaction": {"type": "boolean"},
        },
        "required": [
            "action_type", "content", "target", "mood", "inner_thought",
            "triggers_interaction",
        ],
        "additionalProperties": False,
    }


def _action_to_row(action: CharacterAction) -> ActionRow:
    """Convert an immutable ``CharacterAction`` to an ORM ``ActionRow`` with a new UUID."""
    return ActionRow(
        id=str(uuid.uuid4()),
        tick_id=action.tick_id,
        character_id=action.character_id,
        action_type=action.action_type.value,
        content=action.content,
        target=action.target,
        mood=action.mood,
        inner_thought=action.inner_thought,
        triggers_interaction=action.triggers_interaction,
        created_at=datetime.now(UTC),
    )


async def run_tick(
    tick_id: int,
    world: WorldState,
    client: DeepSeekClient,
    repo: Repository,
    snapshots: SnapshotManager,
    *,
    max_retries: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 16384,
    parent_tick_id: int | None = None,
) -> list[CharacterAction]:
    """Execute a single simulation tick with concurrent LLM calls.

    Steps:
    1. Advance world state: tick_id → *tick_id*, sim_time += tick_interval_hours.
    2. Load system prompt (cached after first call).
    3. Build per-character (user_prompt, tool_schema) snapshots based on the
       tick-start state — perception is frozen before any LLM call.
    4. ``asyncio.gather`` all character LLM calls concurrently.  Each call
       independently retries + repairs JSON; failures fall back to DO_NOTHING.
    5. Sequentially apply mutations (mood / MOVE_TO / appearance) and persist
       action rows in input order — deterministic given the gather result.
    6. Rebuild ``present_characters`` on each location.
    7. Persist full snapshot.
    8. Log per-tick cost summary.

    Args:
        tick_id:        The tick number to execute (must be > world.tick_id at call time).
        world:          Mutable in-memory world state (mutated in-place).
        client:         Configured ``DeepSeekClient``.
        repo:           ``Repository`` for persisting actions and LLM logs.
        snapshots:      ``SnapshotManager`` for persisting the post-tick snapshot.
        max_retries:    Max LLM call attempts per character.
        temperature:    Base sampling temperature (decays on retry in call_with_retry).
        max_tokens:     Max completion tokens per LLM call.
        parent_tick_id: Parent tick for branch/fork tracking (None on linear runs).

    Returns:
        List of ``CharacterAction`` produced this tick (one per character).
    """
    logger.info(
        "Tick %d starting: %d characters, sim_time=%s",
        tick_id,
        len(world.characters),
        world.sim_time.isoformat(),
    )

    # 1. Advance world state.
    # Set tick_id directly to the target tick_id value.
    # Advance sim_time by one tick_interval (we do NOT use advance_time() because
    # that method also increments tick_id by the delta, which would double-count).
    world.tick_id = tick_id
    world.sim_time = world.sim_time + timedelta(hours=world.tick_interval_hours)

    # 2. System prompt (module-level cache).
    system_prompt = load_system_prompt()

    # 3. Freeze per-character perception (prompts + tool schemas) BEFORE any
    # LLM call — concurrent mode requires all characters see the same
    # tick-start state.
    prepared = [
        (char, build_user_prompt(char, world, tick_id, world.sim_time),
         _build_action_tool_schema(char, world))
        for char in world.characters
    ]

    def _call_one(item: tuple) -> Any:
        char_, user_prompt, tool_schema = item
        allowed = set(tool_schema["properties"]["target"]["enum"])
        return call_with_retry(
            client=client,
            system=system_prompt,
            user=user_prompt,
            character_id=char_.id,
            tick_id=tick_id,
            on_log=repo.log_llm,
            max_attempts=max_retries,
            base_temperature=temperature,
            max_tokens=max_tokens,
            tool_schema=tool_schema,
            allowed_targets=allowed,
        )

    # 4. Cache-aware dispatch.
    # DeepSeek prefix cache is established server-side on first request, but
    # concurrent first-tick fires all 5 chars simultaneously — none can see
    # the cache another is establishing.  So we run the FIRST character of
    # each tick sequentially (warmup), then gather the remaining N-1
    # concurrently.  This typically lifts cache hits from ~0% to 60-95% on
    # ticks ≥ 2 with negligible latency cost on tick 1 (~+30s once).
    if not prepared:
        actions: list[CharacterAction] = []
    else:
        first_action = await _call_one(prepared[0])
        rest = await asyncio.gather(*[_call_one(item) for item in prepared[1:]]) if len(prepared) > 1 else []
        actions = [first_action, *rest]

    # 5. Sequential mutation + persistence (deterministic order = world.characters).
    for char, action in zip(world.characters, actions):
        # a. Mood always updates.
        char.current_mood = action.mood

        # b. MOVE_TO: update location only when target is a known location id.
        if action.action_type == ActionType.MOVE_TO and action.target is not None:
            known_loc_ids = {loc.id for loc in world.locations}
            if action.target in known_loc_ids:
                char.current_location = action.target
                logger.debug(
                    "Tick %d: char %s moved to location %s",
                    tick_id,
                    char.id,
                    action.target,
                )
            else:
                logger.debug(
                    "Tick %d: char %s MOVE_TO unknown target %r — location unchanged",
                    tick_id,
                    char.id,
                    action.target,
                )

        # c. SPEAK / REACT: warn when target is not a known character id at this
        # location.  P0 only logs; P1's can_perform() will reject and re-prompt.
        if action.action_type in (ActionType.SPEAK, ActionType.REACT) and action.target:
            present_char_ids = {
                c.id for c in world.characters if c.current_location == char.current_location
            }
            if action.target not in present_char_ids:
                logger.warning(
                    "Tick %d: char %s %s target=%r is not a known character at %s "
                    "(present=%s) — P0 silently accepts, P1 will reject",
                    tick_id,
                    char.id,
                    action.action_type.value,
                    action.target,
                    char.current_location,
                    sorted(present_char_ids - {char.id}),
                )

        # d. Appearance stats.
        char.appearance_count += 1
        char.last_active_tick = tick_id

        # e. Persist action.  (Note: `actions` was built by asyncio.gather;
        # we are NOT appending here — only mutating + saving.)
        repo.save_action(_action_to_row(action))

        logger.info(
            "Tick %d char %s → %s (mood=%r)",
            tick_id,
            char.id,
            action.action_type.value,
            action.mood,
        )

    # 4. Rebuild present_characters on each location.
    for loc in world.locations:
        loc.present_characters = [
            c.id for c in world.characters if c.current_location == loc.id and c.alive
        ]

    # 5. Persist snapshot.
    snapshots.save_snapshot(
        world,
        tick_id,
        action_count=len(actions),
        parent_tick_id=parent_tick_id,
    )

    # 6. Per-tick cost summary.
    _log_tick_summary(tick_id, repo)

    return actions


def _log_tick_summary(tick_id: int, repo: Repository) -> None:
    """Log aggregate token/cost/latency stats for all LLM calls in *tick_id*."""
    logs = repo.get_llm_logs(tick_id=tick_id)
    if not logs:
        logger.info("Tick %d: no LLM logs found (all fallbacks?)", tick_id)
        return

    total_prompt = sum(r.prompt_tokens for r in logs)
    total_response = sum(r.response_tokens for r in logs)
    total_cached = sum(r.cached_tokens for r in logs)
    total_cost = sum(r.cost_usd for r in logs)
    max_latency = max(r.latency_ms for r in logs)

    logger.info(
        "Tick %d summary: calls=%d prompt_tokens=%d response_tokens=%d "
        "cached_tokens=%d cost_usd=%.6f max_latency_ms=%d",
        tick_id,
        len(logs),
        total_prompt,
        total_response,
        total_cached,
        total_cost,
        max_latency,
    )


async def run_simulation(
    n_ticks: int,
    *,
    world: WorldState,
    client: DeepSeekClient,
    repo: Repository,
    snapshots: SnapshotManager,
    start_tick: int = 0,
    sim_config: SimConfig | None = None,
) -> list[CharacterAction]:
    """Run *n_ticks* consecutive ticks starting at *start_tick* + 1.

    Args:
        n_ticks:     Number of ticks to execute.
        world:       Mutable in-memory world state.
        client:      Configured ``DeepSeekClient``.
        repo:        Repository for persistence.
        snapshots:   SnapshotManager for persistence.
        start_tick:  The tick the world is already at.  Simulation runs ticks
                     ``start_tick+1`` … ``start_tick+n_ticks`` (inclusive).
        sim_config:  Optional SimConfig to pull temperature/max_tokens/max_retries
                     from.  Uses scheduler defaults when None.

    Returns:
        Flat list of all ``CharacterAction`` produced across all ticks.
    """
    max_retries = 3
    temperature = 0.7
    max_tokens = 16384
    if sim_config is not None:
        max_retries = sim_config.max_retries
        temperature = sim_config.temperature
        max_tokens = sim_config.max_tokens

    all_actions: list[CharacterAction] = []

    logger.info("run_simulation: n_ticks=%d start_tick=%d", n_ticks, start_tick)

    for i in range(n_ticks):
        tick_id = start_tick + 1 + i
        parent = start_tick if (i == 0 and start_tick > 0) else None

        tick_actions = await run_tick(
            tick_id=tick_id,
            world=world,
            client=client,
            repo=repo,
            snapshots=snapshots,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            parent_tick_id=parent,
        )
        all_actions.extend(tick_actions)

    _log_simulation_summary(start_tick, n_ticks, len(all_actions), repo)
    return all_actions


def _log_simulation_summary(
    start_tick: int, n_ticks: int, total_actions: int, repo: Repository
) -> None:
    """Print aggregate stats across the entire run: cache hit %, total cost, latency."""
    logs = repo.get_llm_logs()  # all logs (may include prior runs in same DB)
    # Filter to logs from ticks just executed.
    run_ticks = set(range(start_tick + 1, start_tick + n_ticks + 1))
    run_logs = [r for r in logs if r.tick_id in run_ticks]

    if not run_logs:
        logger.info(
            "run_simulation complete: %d ticks, %d actions, no LLM logs",
            n_ticks, total_actions,
        )
        return

    total_prompt = sum(r.prompt_tokens for r in run_logs)
    total_response = sum(r.response_tokens for r in run_logs)
    total_cached = sum(r.cached_tokens for r in run_logs)
    total_cost = sum(r.cost_usd for r in run_logs)
    avg_latency = sum(r.latency_ms for r in run_logs) / len(run_logs)
    max_latency = max(r.latency_ms for r in run_logs)
    n_fallbacks = sum(1 for r in run_logs if r.finish_reason == "fallback_do_nothing")
    n_retries = sum(1 for r in run_logs if r.attempt > 1 and r.finish_reason != "fallback_do_nothing")
    cache_pct = (100.0 * total_cached / total_prompt) if total_prompt else 0.0

    logger.info(
        "═══ run_simulation complete ═══ ticks=%d actions=%d llm_calls=%d "
        "retries=%d fallbacks=%d",
        n_ticks, total_actions, len(run_logs), n_retries, n_fallbacks,
    )
    logger.info(
        "  tokens: prompt=%d cached=%d (cache_hit=%.1f%%) response=%d",
        total_prompt, total_cached, cache_pct, total_response,
    )
    logger.info(
        "  latency: avg=%dms max=%dms  |  total cost: $%.5f",
        int(avg_latency), max_latency, total_cost,
    )
