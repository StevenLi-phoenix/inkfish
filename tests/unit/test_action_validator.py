"""Tests for inkfish.character.schema and inkfish.character.validator.

33 parametrized + individual tests covering:
- CharacterAction schema validation (Pydantic)
- _fix_truncated_json / _strip_* helpers
- parse_action_json integration pipeline
- fallback_do_nothing
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.character.validator import (
    _extract_first_json_object,
    _fix_truncated_json,
    _strip_code_fences,
    _strip_control_chars,
    fallback_do_nothing,
    parse_action_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE: dict[str, object] = {
    "character_id": "char_001",
    "tick_id": 0,
    "action_type": "SPEAK",
    "content": "Hello there!",
    "target": "char_002",
    "mood": "happy",
    "inner_thought": "I wonder what they want.",
    "triggers_interaction": False,
}


def _make(**overrides: object) -> dict[str, object]:
    return {**_BASE, **overrides}


# ===========================================================================
# CharacterAction schema
# ===========================================================================


class TestCharacterActionSchema:
    # ------------------------------------------------------------------
    # 1. Valid SPEAK with target
    # ------------------------------------------------------------------
    def test_valid_speak_with_target(self) -> None:
        action = CharacterAction(**_make())
        assert action.action_type == ActionType.SPEAK
        assert action.target == "char_002"

    # ------------------------------------------------------------------
    # 2. SPEAK without target raises ValidationError
    # ------------------------------------------------------------------
    def test_speak_without_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty target"):
            CharacterAction(**_make(target=None))

    # 2b. SPEAK with empty-string target also raises
    def test_speak_with_empty_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty target"):
            CharacterAction(**_make(target=""))

    # 2c. SPEAK with whitespace-only target also raises
    def test_speak_with_whitespace_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty target"):
            CharacterAction(**_make(target="   "))

    # ------------------------------------------------------------------
    # 3. MOVE_TO without target raises
    # ------------------------------------------------------------------
    def test_move_to_without_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty target"):
            CharacterAction(**_make(action_type="MOVE_TO", target=None))

    # ------------------------------------------------------------------
    # 4. REACT without target raises
    # ------------------------------------------------------------------
    def test_react_without_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-empty target"):
            CharacterAction(**_make(action_type="REACT", target=None))

    # ------------------------------------------------------------------
    # 5. THINK with target raises
    # ------------------------------------------------------------------
    def test_think_with_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="must have target=None"):
            CharacterAction(
                **_make(action_type="THINK", target="char_002", triggers_interaction=False)
            )

    # ------------------------------------------------------------------
    # 6. DO_NOTHING with target raises
    # ------------------------------------------------------------------
    def test_do_nothing_with_target_raises(self) -> None:
        with pytest.raises(ValidationError, match="must have target=None"):
            CharacterAction(
                **_make(action_type="DO_NOTHING", target="char_002", triggers_interaction=False)
            )

    # ------------------------------------------------------------------
    # 7. ACT with or without target both pass
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("target", [None, "char_002", "location_x"])
    def test_act_with_or_without_target_both_ok(self, target: str | None) -> None:
        action = CharacterAction(
            **_make(action_type="ACT", target=target, triggers_interaction=False)
        )
        assert action.action_type == ActionType.ACT
        assert action.target == target

    # ------------------------------------------------------------------
    # 8. Extra field is forbidden
    # ------------------------------------------------------------------
    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CharacterAction(**_make(unknown_field="oops"))  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # 9. triggers_interaction=True is only allowed for SPEAK
    # ------------------------------------------------------------------
    @pytest.mark.parametrize(
        "action_type",
        ["THINK", "ACT", "MOVE_TO", "REACT", "DO_NOTHING"],
    )
    def test_triggers_interaction_only_speak(self, action_type: str) -> None:
        kwargs: dict[str, object] = {
            "action_type": action_type,
            "triggers_interaction": True,
        }
        if action_type in {"SPEAK", "MOVE_TO", "REACT"}:
            kwargs["target"] = "char_002"
        else:
            kwargs["target"] = None
        with pytest.raises(ValidationError, match="triggers_interaction"):
            CharacterAction(**_make(**kwargs))

    # ------------------------------------------------------------------
    # 10. content max_length=2000 enforced
    # ------------------------------------------------------------------
    def test_content_max_length_2000(self) -> None:
        long_content = "x" * 2001
        with pytest.raises(ValidationError):
            CharacterAction(**_make(content=long_content))

    def test_content_exactly_2000_is_ok(self) -> None:
        action = CharacterAction(**_make(content="x" * 2000))
        assert len(action.content) == 2000

    # ------------------------------------------------------------------
    # 11. tick_id must be non-negative
    # ------------------------------------------------------------------
    def test_tick_id_must_be_nonneg(self) -> None:
        with pytest.raises(ValidationError):
            CharacterAction(**_make(tick_id=-1))

    def test_tick_id_zero_is_valid(self) -> None:
        action = CharacterAction(**_make(tick_id=0))
        assert action.tick_id == 0

    # ------------------------------------------------------------------
    # 12. frozen=True — model cannot be mutated
    # ------------------------------------------------------------------
    def test_frozen_model_cannot_be_mutated(self) -> None:
        action = CharacterAction(**_make())
        with pytest.raises(ValidationError):
            action.mood = "sad"  # type: ignore[misc]


# ===========================================================================
# Helper functions: _fix_truncated_json, _strip_*, _extract_first_json_object
# ===========================================================================


class TestFixTruncatedJson:
    # ------------------------------------------------------------------
    # 13. Truncated — missing closing brace
    # ------------------------------------------------------------------
    def test_fix_truncated_appends_closing_brace(self) -> None:
        raw = '{"a":1, "b":2'
        result = _fix_truncated_json(raw)
        assert json.loads(result) == {"a": 1, "b": 2}

    # ------------------------------------------------------------------
    # 14. Truncated inside string value
    # ------------------------------------------------------------------
    def test_fix_truncated_appends_quote_and_brace(self) -> None:
        raw = '{"a":"hello'
        result = _fix_truncated_json(raw)
        assert json.loads(result) == {"a": "hello"}

    # ------------------------------------------------------------------
    # 15. Truncated nested array
    # ------------------------------------------------------------------
    def test_fix_truncated_handles_nested_arrays(self) -> None:
        raw = '{"items":[1,2,3'
        result = _fix_truncated_json(raw)
        assert json.loads(result) == {"items": [1, 2, 3]}

    # ------------------------------------------------------------------
    # 16. Braces inside string literals are NOT counted toward the stack
    # ------------------------------------------------------------------
    def test_fix_truncated_braces_inside_string_not_counted(self) -> None:
        # The "{b}" inside the string must NOT be treated as an extra open brace.
        raw = '{"text":"a {b}", "c":1'
        result = _fix_truncated_json(raw)
        parsed = json.loads(result)
        assert parsed == {"text": "a {b}", "c": 1}

    # ------------------------------------------------------------------
    # Idempotent on already-balanced JSON
    # ------------------------------------------------------------------
    def test_fix_truncated_idempotent_on_valid_json(self) -> None:
        valid = '{"x": 42, "y": [1, 2]}'
        result = _fix_truncated_json(valid)
        assert json.loads(result) == {"x": 42, "y": [1, 2]}

    # ------------------------------------------------------------------
    # Empty string
    # ------------------------------------------------------------------
    def test_fix_truncated_empty_string(self) -> None:
        assert _fix_truncated_json("") == ""

    # ------------------------------------------------------------------
    # Escaped quote inside string should not break string tracking
    # ------------------------------------------------------------------
    def test_fix_truncated_escaped_quote_inside_string(self) -> None:
        raw = '{"msg":"say \\"hi\\"'
        result = _fix_truncated_json(raw)
        parsed = json.loads(result)
        assert parsed["msg"] == 'say "hi"'


class TestStripHelpers:
    # ------------------------------------------------------------------
    # 17. _strip_control_chars
    # ------------------------------------------------------------------
    def test_strip_control_chars(self) -> None:
        raw = '{"a":1}\x00\x01\x02'
        assert _strip_control_chars(raw) == '{"a":1}'

    def test_strip_control_chars_preserves_tab_newline_cr(self) -> None:
        text = '{"a":\t"b\nc"}'
        assert _strip_control_chars(text) == text

    # ------------------------------------------------------------------
    # 18. _strip_code_fences — ```json variant
    # ------------------------------------------------------------------
    def test_strip_code_fences_json(self) -> None:
        raw = "```json\n{\"a\":1}\n```"
        assert _strip_code_fences(raw) == '{"a":1}'

    # ------------------------------------------------------------------
    # 19. _strip_code_fences — unlabeled variant
    # ------------------------------------------------------------------
    def test_strip_code_fences_unlabeled(self) -> None:
        raw = "```\n{\"a\":1}\n```"
        assert _strip_code_fences(raw) == '{"a":1}'

    def test_strip_code_fences_no_fence_unchanged(self) -> None:
        raw = '{"a":1}'
        assert _strip_code_fences(raw) == raw

    # ------------------------------------------------------------------
    # 20. _extract_first_json_object — skips leading prose
    # ------------------------------------------------------------------
    def test_extract_first_json_object_skips_prose(self) -> None:
        raw = 'Here is my answer: {"a":1} extra'
        result = _extract_first_json_object(raw)
        assert result is not None
        assert json.loads(result) == {"a": 1}

    def test_extract_first_json_object_no_object_returns_none(self) -> None:
        assert _extract_first_json_object("just text, no braces") is None

    def test_extract_first_json_object_nested(self) -> None:
        raw = 'prefix {"outer":{"inner":1}} suffix'
        result = _extract_first_json_object(raw)
        assert result is not None
        assert json.loads(result) == {"outer": {"inner": 1}}


# ===========================================================================
# parse_action_json integration
# ===========================================================================


def _action_json(**overrides: object) -> str:
    """Build a valid CharacterAction JSON string with optional overrides."""
    base: dict[str, object] = {
        "character_id": "char_001",
        "tick_id": 0,
        "action_type": "SPEAK",
        "content": "Hello!",
        "target": "char_002",
        "mood": "cheerful",
        "inner_thought": "Interesting...",
        "triggers_interaction": False,
    }
    base.update(overrides)
    return json.dumps(base)


class TestParseActionJson:
    # ------------------------------------------------------------------
    # 21. Happy path
    # ------------------------------------------------------------------
    def test_parse_valid_action_returns_model(self) -> None:
        raw = _action_json()
        result = parse_action_json(raw, "char_001", 0)
        assert result is not None
        assert result.action_type == ActionType.SPEAK
        assert result.content == "Hello!"

    # ------------------------------------------------------------------
    # 22. Truncated JSON is repaired and parsed
    # ------------------------------------------------------------------
    def test_parse_truncated_then_recovered(self) -> None:
        raw = _action_json()
        # Strip the final closing brace to simulate truncation.
        truncated = raw[:-1]
        result = parse_action_json(truncated, "char_001", 0)
        assert result is not None
        assert result.character_id == "char_001"

    # ------------------------------------------------------------------
    # 23. Code fence wrapping is stripped
    # ------------------------------------------------------------------
    def test_parse_with_code_fence_recovered(self) -> None:
        fenced = f"```json\n{_action_json()}\n```"
        result = parse_action_json(fenced, "char_001", 0)
        assert result is not None
        assert result.action_type == ActionType.SPEAK

    # ------------------------------------------------------------------
    # 24. LLM-supplied character_id / tick_id are overwritten by caller args
    # ------------------------------------------------------------------
    def test_parse_overrides_character_id_and_tick_id(self) -> None:
        # LLM claims to be a different character at a different tick.
        raw = _action_json(character_id="evil_forgery", tick_id=9999)
        result = parse_action_json(raw, "char_001", 5)
        assert result is not None
        assert result.character_id == "char_001"  # trusted arg wins
        assert result.tick_id == 5               # trusted arg wins

    # ------------------------------------------------------------------
    # 25. Missing required field → None
    # ------------------------------------------------------------------
    def test_parse_missing_required_field_returns_none(self) -> None:
        data: dict[str, object] = json.loads(_action_json())
        del data["mood"]
        result = parse_action_json(json.dumps(data), "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # 26. Invalid action_type enum value → None
    # ------------------------------------------------------------------
    def test_parse_invalid_action_type_returns_none(self) -> None:
        raw = _action_json(action_type="DANCE")
        result = parse_action_json(raw, "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # 27. Target-rule violation → None (SPEAK without target)
    # ------------------------------------------------------------------
    def test_parse_target_rule_violation_returns_none(self) -> None:
        raw = _action_json(target=None)  # SPEAK without target
        result = parse_action_json(raw, "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # 28. Garbage input → None
    # ------------------------------------------------------------------
    def test_parse_garbage_returns_none(self) -> None:
        result = parse_action_json("hello world", "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # 29. Empty string → None
    # ------------------------------------------------------------------
    def test_parse_empty_string_returns_none(self) -> None:
        result = parse_action_json("", "char_001", 0)
        assert result is None

    def test_parse_whitespace_only_returns_none(self) -> None:
        result = parse_action_json("   \n  ", "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # 30. Extra field (extra="forbid") → None
    # ------------------------------------------------------------------
    def test_parse_extra_field_returns_none(self) -> None:
        data: dict[str, object] = json.loads(_action_json())
        data["unexpected_key"] = "surprise"
        result = parse_action_json(json.dumps(data), "char_001", 0)
        assert result is None

    # ------------------------------------------------------------------
    # Prose before JSON (extract_first_json_object path)
    # ------------------------------------------------------------------
    def test_parse_prose_before_json_recovered(self) -> None:
        raw = f"Sure, here is the action: {_action_json()} have a nice day!"
        result = parse_action_json(raw, "char_001", 0)
        assert result is not None
        assert result.action_type == ActionType.SPEAK

    # ------------------------------------------------------------------
    # Control characters stripped before parsing
    # ------------------------------------------------------------------
    def test_parse_strips_control_chars(self) -> None:
        raw = _action_json() + "\x00\x01"
        result = parse_action_json(raw, "char_001", 0)
        assert result is not None

    # ------------------------------------------------------------------
    # DO_NOTHING action (no target, triggers_interaction=False)
    # ------------------------------------------------------------------
    def test_parse_do_nothing_action(self) -> None:
        raw = _action_json(
            action_type="DO_NOTHING",
            content="",
            target=None,
            triggers_interaction=False,
        )
        result = parse_action_json(raw, "char_001", 0)
        assert result is not None
        assert result.action_type == ActionType.DO_NOTHING
        assert result.target is None

    # ------------------------------------------------------------------
    # THINK action (no target)
    # ------------------------------------------------------------------
    def test_parse_think_action(self) -> None:
        raw = _action_json(
            action_type="THINK",
            target=None,
            triggers_interaction=False,
        )
        result = parse_action_json(raw, "char_001", 0)
        assert result is not None
        assert result.action_type == ActionType.THINK

    # ------------------------------------------------------------------
    # triggers_interaction=True on non-SPEAK → None
    # ------------------------------------------------------------------
    def test_parse_triggers_interaction_non_speak_returns_none(self) -> None:
        raw = _action_json(
            action_type="ACT",
            target=None,
            triggers_interaction=True,
        )
        result = parse_action_json(raw, "char_001", 0)
        assert result is None


# ===========================================================================
# fallback_do_nothing
# ===========================================================================


class TestFallbackDoNothing:
    # ------------------------------------------------------------------
    # 31. Returned action passes schema validation
    # ------------------------------------------------------------------
    def test_fallback_returns_valid_do_nothing(self) -> None:
        action = fallback_do_nothing("char_001", 3)
        assert isinstance(action, CharacterAction)
        assert action.action_type == ActionType.DO_NOTHING
        assert action.character_id == "char_001"
        assert action.tick_id == 3
        assert action.target is None
        assert action.triggers_interaction is False

    # ------------------------------------------------------------------
    # 32. Provided mood is preserved
    # ------------------------------------------------------------------
    def test_fallback_uses_provided_mood(self) -> None:
        action = fallback_do_nothing("char_001", 0, mood="anxious")
        assert action.mood == "anxious"

    # ------------------------------------------------------------------
    # 33. Empty mood string falls back to "neutral"
    # ------------------------------------------------------------------
    def test_fallback_default_mood_when_empty(self) -> None:
        action = fallback_do_nothing("char_001", 0, mood="")
        assert action.mood == "neutral"

    def test_fallback_whitespace_mood_falls_back_to_neutral(self) -> None:
        action = fallback_do_nothing("char_001", 0, mood="   ")
        assert action.mood == "neutral"

    def test_fallback_default_mood_kwarg(self) -> None:
        action = fallback_do_nothing("char_001", 0)
        assert action.mood == "neutral"
