"""inkfish.character.validator — JSON repair and CharacterAction parsing.

The LLM may return:
- Valid JSON — fast path.
- Truncated JSON (missing closing braces/brackets/quotes) — repaired.
- JSON wrapped in ```json ... ``` fences — stripped then repaired.
- Prose followed by a JSON object — prose stripped.
- Garbage (missing required fields, wrong types, bad enum values) — None.

Security: ``parse_action_json`` always overwrites ``character_id`` and
``tick_id`` with the trusted caller-supplied values so the LLM cannot forge
its identity or claim a different tick.

Port of mirofish simulation_config_generator.py:483-533 with improvements:
- Stack-based brace/bracket tracking (skips chars inside string literals)
- Strips code fences and control characters before repairing
- Does NOT mangle already-valid JSON (idempotent on balanced input)
"""

from __future__ import annotations

import json
import logging
import re

from .schema import ActionType, CharacterAction

logger = logging.getLogger(__name__)

# Control characters to strip: \x00-\x08, \x0b, \x0c, \x0e-\x1f
# We intentionally keep \t (\x09), \n (\x0a), \r (\x0d).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Matches optional whitespace + ```json or ``` + content + ``` at the end.
_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?([\s\S]*?)\n?\s*```\s*$",
    re.DOTALL,
)


def _strip_control_chars(s: str) -> str:
    """Remove non-printable control characters while preserving \\t, \\n, \\r."""
    return _CONTROL_CHARS_RE.sub("", s)


def _strip_code_fences(s: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    m = _CODE_FENCE_RE.match(s)
    if m:
        return m.group(1)
    return s


def _extract_first_json_object(s: str) -> str | None:
    """Return the first balanced ``{ ... }`` substring found in *s*.

    Used when the model emits prose before or after the JSON object.
    Returns ``None`` if no balanced object is found.
    """
    start: int | None = None
    depth = 0
    in_string = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            if ch == "\\" and i + 1 < len(s):
                i += 2  # skip escaped char
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    return s[start : i + 1]
        i += 1
    return None


def _fix_truncated_json(raw: str) -> str:
    """Best-effort repair of a truncated JSON string.

    Algorithm (improved port of mirofish _fix_truncated_json):
    1. Strip surrounding whitespace.
    2. Walk the string character by character, tracking:
       - Whether we are inside a string literal (toggle on unescaped ``"``)
       - A stack of unmatched ``{`` and ``[`` characters
    3. If the walk ends mid-string (``in_string=True``), append a closing ``"``.
    4. Pop the remaining open-bracket stack, appending ``]`` or ``}`` as needed.

    The string-aware walk means braces/brackets INSIDE string values are
    never counted toward the open stack, so valid JSON is left unchanged.

    Does NOT attempt to fix missing colons, commas, or wrong types — those
    cause ``json.loads`` to fail and the caller returns ``None``.
    """
    s = raw.strip()
    if not s:
        return s

    stack: list[str] = []  # unmatched openers: '{' or '['
    in_string = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string:
            if ch == "\\" and i + 1 < len(s):
                i += 2  # skip escaped character (including escaped quote)
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("{")
            elif ch == "[":
                stack.append("[")
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
        i += 1

    # Close an unterminated string literal.
    if in_string:
        s += '"'

    # Close unmatched openers in LIFO order.
    for opener in reversed(stack):
        s += "]" if opener == "[" else "}"

    return s


def parse_action_json(raw: str, character_id: str, tick_id: int) -> CharacterAction | None:
    """Parse *raw* LLM output into a ``CharacterAction``.

    Pipeline:
    1. Strip code fences.
    2. Strip control characters.
    3. Attempt ``json.loads``; on failure apply ``_fix_truncated_json`` and retry.
    4. Extract first JSON object if step 3 still fails (prose-before-JSON case).
    5. Build ``CharacterAction(**data)`` — always overwriting ``character_id``
       and ``tick_id`` from the trusted caller arguments.

    Returns ``None`` on any irrecoverable failure (validation error, missing
    required fields, bad enum, target-rule violation, …).  The caller layer
    (``retry.py``) decides whether to retry or call ``fallback_do_nothing``.
    """
    if not raw or not raw.strip():
        logger.debug("parse_action_json: received empty input")
        return None

    text = _strip_code_fences(raw.strip())
    text = _strip_control_chars(text)

    # Try to parse as-is first (happy path).
    data: object = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Attempt truncation repair.
        repaired = _fix_truncated_json(text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            # Last-resort: look for the first balanced { ... } in the text.
            extracted = _extract_first_json_object(text)
            if extracted is None:
                logger.debug(
                    "parse_action_json: could not extract JSON object from raw=%r",
                    raw[:200],
                )
                return None
            try:
                data = json.loads(extracted)
            except json.JSONDecodeError:
                logger.debug(
                    "parse_action_json: extracted fragment still invalid JSON: %r",
                    extracted[:200],
                )
                return None

    if not isinstance(data, dict):
        logger.debug("parse_action_json: top-level JSON is not an object (got %s)", type(data))
        return None

    # Overwrite character_id and tick_id with trusted caller values — never
    # let the LLM forge these fields.
    data["character_id"] = character_id
    data["tick_id"] = tick_id

    # Tool-call schema represents "no target" as an empty string (JSON Schema
    # strict enum can't cleanly mix string + null).  Normalise back to None
    # so the Pydantic target-rule validators apply correctly.
    if data.get("target") == "":
        data["target"] = None

    try:
        return CharacterAction(**data)
    except Exception as exc:  # ValidationError or TypeError from extra fields via Pydantic
        logger.debug(
            "parse_action_json: CharacterAction validation failed for char=%s tick=%d: %s",
            character_id,
            tick_id,
            exc,
        )
        return None


def fallback_do_nothing(character_id: str, tick_id: int, mood: str = "neutral") -> CharacterAction:
    """Return a structurally valid DO_NOTHING action.

    Used when all retry attempts are exhausted and the LLM output cannot be
    repaired.  The ``mood`` argument defaults to ``"neutral"``; if an empty
    string is passed it is coerced to ``"neutral"`` so the Pydantic
    ``min_length=1`` constraint is always satisfied.
    """
    safe_mood = mood.strip() if mood and mood.strip() else "neutral"
    return CharacterAction(
        character_id=character_id,
        tick_id=tick_id,
        action_type=ActionType.DO_NOTHING,
        content="",
        target=None,
        mood=safe_mood,
        inner_thought="",
        triggers_interaction=False,
    )
