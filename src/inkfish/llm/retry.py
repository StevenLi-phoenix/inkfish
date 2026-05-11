"""inkfish.llm.retry — Retry + JSON-repair layer wrapping DeepSeekClient.

Contract:
- ``call_with_retry`` NEVER raises.  On terminal failure it returns a
  ``fallback_do_nothing`` action so the simulation loop can continue.
- Every attempt (success OR failure) emits an ``LLMLogRow`` via ``on_log``
  to preserve a complete audit trail.  A synthetic "fallback" row is emitted
  when all attempts are exhausted.

Retry strategy:
  Attempt 1: base_temperature,     original user prompt
  Attempt 2: base_temperature-0.1, user prompt prefixed with corrective note
  Attempt 3: base_temperature-0.2, same corrective prefix
  …up to max_attempts (default 3).

Transient network errors (429, connection, timeout) are handled by an inner
tenacity retry on each attempt.  JSON parse failures advance the outer loop.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from openai import APIConnectionError, APITimeoutError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from inkfish.character.schema import CharacterAction
from inkfish.character.validator import fallback_do_nothing, parse_action_json
from inkfish.storage.models import LLMLogRow

from .deepseek import DeepSeekClient, LLMResult

logger = logging.getLogger(__name__)

# Transient openai errors that should trigger tenacity inner-retry.
_TRANSIENT_ERRORS = (RateLimitError, APIConnectionError, APITimeoutError)

# Corrective prefix injected into the user prompt on retry (non-first attempts).
_CORRECTION_PREFIX = "上次响应非法 JSON: {error}. 只输出 JSON. 不要 markdown 围栏. 不要散文.\n\n"


def _make_log_row(
    *,
    tick_id: int,
    character_id: str,
    model: str,
    system: str,
    user: str,
    result: LLMResult | None = None,
    error: str | None = None,
    attempt: int,
    finish_reason: str = "",
) -> LLMLogRow:
    """Build an ``LLMLogRow`` from call parameters and an optional result."""
    row = LLMLogRow(
        id=str(uuid.uuid4()),
        tick_id=tick_id,
        character_id=character_id,
        provider="deepseek",
        model=model,
        prompt=f"[system]\n{system}\n\n[user]\n{user}",
        response=result.content if result is not None else "",
        prompt_tokens=result.prompt_tokens if result is not None else 0,
        response_tokens=result.response_tokens if result is not None else 0,
        cached_tokens=result.cached_tokens if result is not None else 0,
        cost_usd=result.cost_usd if result is not None else 0.0,
        latency_ms=result.latency_ms if result is not None else 0,
        finish_reason=result.finish_reason if result is not None else finish_reason,
        error=error,
        attempt=attempt,
        created_at=datetime.now(UTC),
    )
    return row


def call_with_retry(
    client: DeepSeekClient,
    system: str,
    user: str,
    character_id: str,
    tick_id: int,
    *,
    on_log: Callable[[LLMLogRow], None],
    max_attempts: int = 3,
    base_temperature: float = 0.7,
    max_tokens: int = 800,
) -> CharacterAction:
    """Call DeepSeek with retry and JSON repair.

    Parameters:
        client:           Configured ``DeepSeekClient`` instance.
        system:           System prompt.
        user:             User prompt (MUST contain "json" for DeepSeek JSON mode).
        character_id:     Trusted character identifier — overrides LLM output.
        tick_id:          Current simulation tick — overrides LLM output.
        on_log:           Callback invoked with each ``LLMLogRow`` (success or failure).
        max_attempts:     Maximum outer loop iterations (default 3).
        base_temperature: Starting temperature; decremented by 0.1 each attempt.
        max_tokens:       Max completion tokens per call.

    Returns:
        A valid ``CharacterAction``.  Never raises.
    """
    last_parse_error: str = "no_attempts"
    current_user = user
    # DeepSeek v4-pro is a reasoner: reasoning_tokens consume the budget before
    # any content is emitted.  If finish_reason == "length" with empty content,
    # we expand the budget on the next attempt (capped at 8000, DeepSeek's max).
    current_max_tokens = max_tokens
    _MAX_TOKENS_CEIL = 8000

    for attempt in range(1, max_attempts + 1):
        temperature = max(0.0, base_temperature - (attempt - 1) * 0.1)

        # Inner helper: handles transient network errors with tenacity.
        # Default arguments bind the loop-local values at definition time,
        # avoiding the B023 "closure over loop variable" bug.
        _temp = temperature
        _user = current_user
        _max_tok = current_max_tokens

        @retry(
            retry=retry_if_exception_type(_TRANSIENT_ERRORS),
            wait=wait_random_exponential(min=1, max=10),
            stop=stop_after_attempt(5),
            reraise=True,
        )
        def _network_call(
            _bound_user: str = _user,
            _bound_temp: float = _temp,
            _bound_max_tok: int = _max_tok,
        ) -> LLMResult:
            """Execute one HTTP call; returns LLMResult."""
            return client.complete_json(
                system,
                _bound_user,
                temperature=_bound_temp,
                max_tokens=_bound_max_tok,
            )

        # --- Execute the network call ---
        result: LLMResult | None = None
        network_error: str | None = None

        try:
            result = _network_call()
        except Exception as exc:
            # Transient errors exhausted all inner retries, or a non-transient
            # error occurred (e.g. 5xx).  Log and advance to next outer attempt.
            network_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "call_with_retry: network error on attempt %d/%d for char=%s tick=%d: %s",
                attempt,
                max_attempts,
                character_id,
                tick_id,
                network_error,
            )
            row = _make_log_row(
                tick_id=tick_id,
                character_id=character_id,
                model=client.model,
                system=system,
                user=_user,
                result=None,
                error=network_error,
                attempt=attempt,
                finish_reason="error",
            )
            on_log(row)
            last_parse_error = network_error
            # Build corrective prefix for next attempt.
            current_user = _CORRECTION_PREFIX.format(error=network_error) + user
            continue

        # --- Attempt JSON parse ---
        assert result is not None  # mypy: guaranteed by successful _network_call
        action = parse_action_json(result.content, character_id, tick_id)

        if action is not None:
            # SUCCESS — emit log and return.
            row = _make_log_row(
                tick_id=tick_id,
                character_id=character_id,
                model=client.model,
                system=system,
                user=_user,
                result=result,
                error=None,
                attempt=attempt,
            )
            on_log(row)
            logger.debug(
                "call_with_retry: success on attempt %d/%d for char=%s tick=%d " "action_type=%s",
                attempt,
                max_attempts,
                character_id,
                tick_id,
                action.action_type.value,
            )
            return action

        # PARSE FAILURE — log the failed attempt and prepare retry.
        truncated_by_length = result.finish_reason == "length" and not result.content.strip()
        if truncated_by_length:
            parse_error = (
                f"length_truncation: response_tokens={result.response_tokens} "
                f"exhausted max_tokens={current_max_tokens} before any content "
                f"(v4-pro reasoning consumed full budget)"
            )
        else:
            parse_error = f"invalid_json_or_schema: content={result.content[:120]!r}"
        logger.warning(
            "call_with_retry: JSON parse failed on attempt %d/%d for char=%s tick=%d "
            "(finish_reason=%s, truncated=%s)",
            attempt,
            max_attempts,
            character_id,
            tick_id,
            result.finish_reason,
            truncated_by_length,
        )
        row = _make_log_row(
            tick_id=tick_id,
            character_id=character_id,
            model=client.model,
            system=system,
            user=_user,
            result=result,
            error=parse_error,
            attempt=attempt,
        )
        on_log(row)
        last_parse_error = parse_error

        # On length truncation, expand the token budget for the next attempt
        # (×1.5, capped at 8000) instead of changing the prompt — the model
        # didn't fail to follow instructions, it just ran out of room.
        if truncated_by_length:
            current_max_tokens = min(int(current_max_tokens * 1.5), _MAX_TOKENS_CEIL)
            logger.info(
                "call_with_retry: expanding max_tokens to %d for next attempt",
                current_max_tokens,
            )
        # Build corrective prefix for the next attempt.
        current_user = _CORRECTION_PREFIX.format(error=parse_error) + user

    # --- All attempts exhausted — emit synthetic fallback log row ---
    logger.error(
        "call_with_retry: all %d attempts failed for char=%s tick=%d — "
        "returning DO_NOTHING fallback. last_error=%s",
        max_attempts,
        character_id,
        tick_id,
        last_parse_error,
    )
    fallback_row = _make_log_row(
        tick_id=tick_id,
        character_id=character_id,
        model=client.model,
        system=system,
        user=user,  # original, not the corrective prefix
        result=None,
        error="all_attempts_failed",
        attempt=max_attempts + 1,  # synthetic — beyond normal range
        finish_reason="fallback_do_nothing",
    )
    on_log(fallback_row)

    return fallback_do_nothing(character_id, tick_id)
