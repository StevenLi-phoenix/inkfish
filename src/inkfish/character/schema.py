"""inkfish.character.schema — Pydantic model for character action output.

CharacterAction is the sole contract between the LLM and the simulation
engine.  It is frozen (immutable) so it can be safely passed around and
cached without accidental mutation.

P0 notes:
- `can_perform()` auth check is NOT implemented here (P1).
- `triggers_interaction` is restricted to SPEAK only (broadened in P1).
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionType(str, Enum):
    SPEAK = "SPEAK"
    THINK = "THINK"
    ACT = "ACT"
    MOVE_TO = "MOVE_TO"
    REACT = "REACT"
    DO_NOTHING = "DO_NOTHING"


# Action types that MUST have a non-empty target.
_REQUIRES_TARGET: frozenset[ActionType] = frozenset(
    {ActionType.SPEAK, ActionType.MOVE_TO, ActionType.REACT}
)

# Action types that MUST NOT have a target.
_FORBIDS_TARGET: frozenset[ActionType] = frozenset({ActionType.THINK, ActionType.DO_NOTHING})


class CharacterAction(BaseModel):
    """Structured output from a single character LLM call.

    Field constraints:
    - ``character_id``: non-empty string (never let the LLM forge this).
    - ``tick_id``: non-negative integer.
    - ``content``: the visible action text, max 2 000 chars.
    - ``target``: character/location ID; required for SPEAK/MOVE_TO/REACT,
      forbidden for THINK/DO_NOTHING, optional for ACT.
    - ``mood``: short post-action mood label (1–100 chars).
    - ``inner_thought``: private monologue, never visible to other characters.
    - ``triggers_interaction``: P0 — only SPEAK may set this True.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str = Field(min_length=1)
    tick_id: int = Field(ge=0)
    action_type: ActionType
    content: str = Field(max_length=2000)
    target: str | None = None
    mood: str = Field(min_length=1, max_length=100)
    inner_thought: str = Field(default="", max_length=2000)
    triggers_interaction: bool = False

    @model_validator(mode="after")
    def _check_target_consistency(self) -> Self:
        """Enforce target presence/absence rules per action type."""
        at = self.action_type
        t = self.target

        if at in _REQUIRES_TARGET:
            if not t or not t.strip():
                raise ValueError(f"action_type {at.value} requires a non-empty target, got {t!r}")

        if at in _FORBIDS_TARGET:
            if t is not None:
                raise ValueError(f"action_type {at.value} must have target=None, got {t!r}")

        return self

    @model_validator(mode="after")
    def _check_triggers_interaction_rule(self) -> Self:
        """P0: triggers_interaction may only be True for SPEAK actions."""
        if self.triggers_interaction and self.action_type != ActionType.SPEAK:
            raise ValueError(
                f"triggers_interaction=True is only allowed for SPEAK actions "
                f"(got action_type={self.action_type.value})"
            )
        return self
