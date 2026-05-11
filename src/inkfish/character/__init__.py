"""inkfish.character — character agent schemas, context assembly, and action validation."""

from inkfish.character.context import (
    build_memory_block,
    build_perception_block,
    build_persona_block,
    build_user_prompt,
    load_system_prompt,
)

__all__ = [
    "build_memory_block",
    "build_perception_block",
    "build_persona_block",
    "build_user_prompt",
    "load_system_prompt",
]
