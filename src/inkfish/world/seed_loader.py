"""inkfish.world.seed_loader — Load and persist the world seed file.

The seed file (``data/seed/world.json``) defines the starting state of the
simulation: a single location plus five differentiated characters.  This
module provides two entry points:

* :func:`load_seed_file` — parse and validate only, no DB access.
* :func:`seed_world` — parse, reset the DB, persist to tick_id=0, save snapshot.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .state import Character, Location, WorldState

if TYPE_CHECKING:
    from inkfish.storage.repository import Repository
    from inkfish.storage.snapshot import SnapshotManager

logger = logging.getLogger(__name__)

# Canonical set of 16 MBTI types (uppercase)
_VALID_MBTI: frozenset[str] = frozenset(
    {
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP",
    }
)

# Minimum field lengths (characters)
_MIN_BACKGROUND_LEN: int = 400
_MIN_PERSONALITY_LEN: int = 150
_MIN_APPEARANCE_LEN: int = 80


def _validate_character(raw: dict[str, Any]) -> None:
    """Raise :class:`ValueError` if *raw* is missing required fields or has bad values."""
    required = ("id", "name", "mbti", "age", "background", "appearance", "personality",
                "current_location", "current_mood", "routine")
    for field_name in required:
        if field_name not in raw:
            char_id = raw.get("id", "<unknown>")
            raise ValueError(
                f"Character seed is missing required field '{field_name}': {char_id}"
            )

    mbti = str(raw["mbti"]).upper()
    if mbti not in _VALID_MBTI:
        raise ValueError(
            f"Character '{raw.get('id')}' has invalid MBTI '{raw['mbti']}'. "
            f"Must be one of: {sorted(_VALID_MBTI)}"
        )


def _parse_character(raw: dict[str, Any]) -> Character:
    """Convert a validated character dict to a :class:`Character` dataclass."""
    return Character(
        id=str(raw["id"]),
        name=str(raw["name"]),
        mbti=str(raw["mbti"]).upper(),
        age=int(raw["age"]),
        background=str(raw["background"]),
        appearance=str(raw["appearance"]),
        personality=str(raw["personality"]),
        current_location=str(raw["current_location"]),
        current_mood=str(raw["current_mood"]),
        routine=dict(raw["routine"]),
    )


def _validate_location(raw: dict[str, Any]) -> None:
    """Raise :class:`ValueError` if *raw* is missing required location fields."""
    required = ("id", "name", "description", "layer")
    for field_name in required:
        if field_name not in raw:
            loc_id = raw.get("id", "<unknown>")
            raise ValueError(
                f"Location seed is missing required field '{field_name}': {loc_id}"
            )


def _parse_location(raw: dict[str, Any]) -> Location:
    """Convert a validated location dict to a :class:`Location` dataclass."""
    return Location(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw["description"]),
        layer=str(raw.get("layer", "physical")),
        present_characters=[str(c) for c in raw.get("present_characters", [])],
        connected_to=[str(c) for c in raw.get("connected_to", [])],
    )


def load_seed_file(path: Path | str) -> WorldState:
    """Read a seed JSON file and construct an in-memory :class:`WorldState` at tick_id=0.

    Args:
        path: Path to the seed JSON file (e.g. ``data/seed/world.json``).

    Returns:
        A :class:`WorldState` with ``tick_id=0`` populated from the seed.

    Raises:
        ValueError: If any required field is missing or has an invalid value.
        FileNotFoundError: If *path* does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    seed_path = Path(path)
    logger.info("Loading seed file: %s", seed_path)

    with seed_path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    # Parse sim_time
    raw_time = data.get("sim_time", "2026-01-15T08:00:00Z")
    sim_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    if sim_time.tzinfo is None:
        sim_time = sim_time.replace(tzinfo=UTC)

    # Parse location (single location block)
    raw_loc = data.get("location")
    if raw_loc is None:
        raise ValueError("Seed file is missing top-level 'location' key.")
    _validate_location(raw_loc)
    location = _parse_location(raw_loc)

    # Parse characters
    raw_chars = data.get("characters")
    if not raw_chars:
        raise ValueError("Seed file is missing or has empty 'characters' list.")

    characters: list[Character] = []
    for raw_char in raw_chars:
        _validate_character(raw_char)
        characters.append(_parse_character(raw_char))

    # Build location's present_characters from the character list
    char_ids_at_loc = [c.id for c in characters if c.current_location == location.id]
    location.present_characters = char_ids_at_loc

    world = WorldState(
        tick_id=0,
        sim_time=sim_time,
        characters=characters,
        locations=[location],
    )
    logger.info(
        "Seed loaded: tick=0, sim_time=%s, chars=%d, locs=%d",
        sim_time.isoformat(),
        len(characters),
        len(world.locations),
    )
    return world


def seed_world(
    path: Path | str,
    repo: Repository,
    snapshots: SnapshotManager,
) -> WorldState:
    """Load the seed file, wipe the DB, and persist tick_id=0.

    Steps:
        1. Parse ``path`` → :class:`WorldState`
        2. ``snapshots.reset(to_tick_id=-1)`` — delete ALL existing simulation data
        3. Upsert each character and location at tick_id=0 via the repo
        4. Save snapshot for tick_id=0 (0 actions at seed time)

    Args:
        path: Path to the seed JSON file.
        repo: :class:`~inkfish.storage.repository.Repository` instance.
        snapshots: :class:`~inkfish.storage.snapshot.SnapshotManager` instance.

    Returns:
        The constructed :class:`WorldState` (in-memory; caller may use it directly).
    """
    world = load_seed_file(path)

    logger.info("Resetting DB to fresh slate before seeding...")
    snapshots.reset(to_tick_id=-1)

    logger.info("Upserting %d characters and %d locations at tick_id=0...",
                len(world.characters), len(world.locations))
    for char in world.characters:
        repo.upsert_character(char, tick_id=0)
    for loc in world.locations:
        repo.upsert_location(loc, tick_id=0)

    snapshots.save_snapshot(world, tick_id=0, action_count=0)
    logger.info("Seed complete: tick_id=0 written to DB.")

    return world
