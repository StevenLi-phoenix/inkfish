"""Unit tests for inkfish.llm.retry.call_with_retry.

Uses a FakeDeepSeekClient (not respx) — a lightweight scriptable fake whose
``complete_json`` returns scripted LLMResult objects or raises scripted
exceptions.  This isolates retry semantics from wire-protocol details.

Design notes:
- LLMLogRow rows are collected via the ``on_log`` callback.
- The fake client records temperatures used on each call.
- call_with_retry MUST never raise — all failures → DO_NOTHING fallback.
"""

from __future__ import annotations

from typing import Any

import pytest
from openai import APIConnectionError, RateLimitError

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.llm.deepseek import LLMResult
from inkfish.llm.retry import call_with_retry
from inkfish.storage.models import LLMLogRow

# ---------------------------------------------------------------------------
# FakeDeepSeekClient
# ---------------------------------------------------------------------------

_VALID_JSON = (
    '{"action_type": "THINK", "content": "thinking...", '
    '"mood": "curious", "inner_thought": "", "triggers_interaction": false}'
)

_INVALID_JSON = "not json at all {{{broken"


def _make_result(
    content: str = _VALID_JSON,
    prompt_tokens: int = 100,
    response_tokens: int = 50,
    cached_tokens: int = 0,
    cost_usd: float = 0.001,
    latency_ms: int = 120,
    finish_reason: str = "stop",
) -> LLMResult:
    return LLMResult(
        content=content,
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        cached_tokens=cached_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
    )


class FakeDeepSeekClient:
    """Scriptable fake for DeepSeekClient.

    ``scripts`` is a list of either:
    - An ``LLMResult`` to return on that call, or
    - An exception instance/class to raise.

    Calls beyond the script list raise ``IndexError`` to catch test bugs.
    Records temperatures used in ``recorded_temps``.
    """

    model: str = "deepseek-v4-pro"

    def __init__(self, scripts: list[LLMResult | BaseException]) -> None:
        self._scripts = list(scripts)
        self._call_index = 0
        self.recorded_temps: list[float] = []

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> LLMResult:
        self.recorded_temps.append(temperature)
        if self._call_index >= len(self._scripts):
            raise IndexError(f"FakeDeepSeekClient: no script for call #{self._call_index + 1}")
        item = self._scripts[self._call_index]
        self._call_index += 1
        if isinstance(item, BaseException):
            raise item
        return item

    async def complete_with_tool(
        self,
        system: str,
        user: str,
        tool_schema: dict,
        *,
        tool_name: str = "submit_action",
        tool_description: str = "",
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> LLMResult:
        """Same scripted behaviour as complete_json — tool_schema is ignored
        by the fake; tests that use tool_schema only need to verify the path
        is taken, which they do by inspecting recorded_temps / call_index."""
        return await self.complete_json(
            system, user, temperature=temperature, max_tokens=max_tokens
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_logs(logs: list[LLMLogRow]) -> None:
    """Simple collector callback for on_log."""
    # Only used as a side-effect target; logs list is mutated in-place.
    pass


async def _run(
    client: FakeDeepSeekClient,
    *,
    character_id: str = "char_001",
    tick_id: int = 1,
    max_attempts: int = 3,
    base_temperature: float = 0.7,
) -> tuple[CharacterAction, list[LLMLogRow]]:
    """Helper: run call_with_retry, collect logs, return (action, log_rows)."""
    rows: list[LLMLogRow] = []
    action = await call_with_retry(
        client,  # type: ignore[arg-type]  # FakeDeepSeekClient is duck-typed
        system="You output json.",
        user="Return a json action object.",
        character_id=character_id,
        tick_id=tick_id,
        on_log=rows.append,
        max_attempts=max_attempts,
        base_temperature=base_temperature,
    )
    return action, rows


# ---------------------------------------------------------------------------
# Test 1: first attempt success — one log row, attempt=1, no error
# ---------------------------------------------------------------------------


async def test_first_attempt_success_no_retry() -> None:
    """Fake returns valid JSON on attempt 1 → one log row, attempt=1, no error."""
    client = FakeDeepSeekClient([_make_result()])
    action, rows = await _run(client)

    assert isinstance(action, CharacterAction)
    assert action.action_type == ActionType.THINK
    assert len(rows) == 1
    assert rows[0].attempt == 1
    assert rows[0].error is None


# ---------------------------------------------------------------------------
# Test 2: invalid JSON on attempt 1, valid on attempt 2 → success
# ---------------------------------------------------------------------------


async def test_retries_on_invalid_json_then_succeeds() -> None:
    """Attempt 1 returns garbage, attempt 2 returns valid JSON."""
    client = FakeDeepSeekClient([_make_result(content=_INVALID_JSON), _make_result()])
    action, rows = await _run(client)

    assert isinstance(action, CharacterAction)
    assert action.action_type == ActionType.THINK
    # Two log rows: first has error, second does not.
    assert len(rows) == 2
    assert rows[0].error is not None
    assert rows[1].error is None
    assert rows[1].attempt == 2


# ---------------------------------------------------------------------------
# Test 3: temperature decays across attempts
# ---------------------------------------------------------------------------


async def test_temperature_decays_across_attempts() -> None:
    """Temperature decreases by 0.1 per attempt: 0.7 → 0.6 → 0.5."""
    client = FakeDeepSeekClient(
        [
            _make_result(content=_INVALID_JSON),
            _make_result(content=_INVALID_JSON),
            _make_result(),  # succeeds on attempt 3
        ]
    )
    await _run(client, max_attempts=3, base_temperature=0.7)

    assert len(client.recorded_temps) == 3
    assert abs(client.recorded_temps[0] - 0.7) < 1e-9
    assert abs(client.recorded_temps[1] - 0.6) < 1e-9
    assert abs(client.recorded_temps[2] - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: all attempts fail → DO_NOTHING fallback + 4 log rows
# ---------------------------------------------------------------------------


async def test_all_attempts_fail_returns_fallback_do_nothing() -> None:
    """All 3 attempts return garbage → DO_NOTHING action + 4 log rows (3 + 1 synthetic)."""
    client = FakeDeepSeekClient(
        [
            _make_result(content=_INVALID_JSON),
            _make_result(content=_INVALID_JSON),
            _make_result(content=_INVALID_JSON),
        ]
    )
    action, rows = await _run(client, max_attempts=3)

    assert isinstance(action, CharacterAction)
    assert action.action_type == ActionType.DO_NOTHING
    # 3 failed attempt rows + 1 synthetic fallback row.
    assert len(rows) == 4
    # Synthetic fallback row.
    fallback_row = rows[-1]
    assert fallback_row.error == "all_attempts_failed"
    assert fallback_row.finish_reason == "fallback_do_nothing"


# ---------------------------------------------------------------------------
# Test 5: 429 → inner tenacity retries, then succeeds on next outer attempt
# ---------------------------------------------------------------------------


async def test_429_retries_internally_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """RateLimitError triggers tenacity inner-retry and the call ultimately succeeds.

    Strategy: patch ``tenacity.nap.sleep`` to eliminate backoff delays, then
    exhaust the inner tenacity retries (5x) on outer attempt 1.  Outer attempt 2
    succeeds, producing 2 log rows total:
    - row 1: failed outer attempt (network error)
    - row 2: successful outer attempt

    Implementation note: tenacity's ``Retrying`` calls ``self.sleep`` which
    defaults to ``tenacity.nap.sleep``.  Because the ``@retry``-decorated
    ``_network_call`` closure is re-created on each outer loop iteration (not
    cached at module level), patching ``tenacity.nap.sleep`` does NOT intercept
    the backoff.  Instead we patch ``time.sleep`` directly, which
    ``tenacity.nap.sleep`` delegates to.
    """
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _seconds: None)

    import httpx as _httpx

    _req = _httpx.Request("POST", "https://api.deepseek.com")
    rate_limit_error = RateLimitError(
        message="rate limit",
        response=_httpx.Response(429, request=_req),
        body=None,
    )

    # Script: 5 RateLimitErrors (exhaust tenacity stop_after_attempt(5)) +
    # 1 success for outer attempt 2.
    scripts: list[LLMResult | BaseException] = [rate_limit_error] * 5 + [_make_result()]
    client = FakeDeepSeekClient(scripts)

    action, rows = await _run(client, max_attempts=3)

    assert isinstance(action, CharacterAction)
    assert action.action_type == ActionType.THINK
    # 1 failed outer attempt (network error) + 1 successful outer attempt.
    assert len(rows) == 2
    assert rows[0].error is not None
    assert rows[1].error is None


# ---------------------------------------------------------------------------
# Test 6: corrective prefix added on retry
# ---------------------------------------------------------------------------


async def test_correction_prefix_added_on_retry() -> None:
    """On attempt 2, the user prompt includes a corrective prefix mentioning 'JSON'."""
    user_prompts: list[str] = []

    class RecordingFakeClient(FakeDeepSeekClient):
        async def complete_json(self, system: str, user: str, **kwargs: Any) -> LLMResult:
            user_prompts.append(user)
            return await super().complete_json(system, user, **kwargs)

    client = RecordingFakeClient([_make_result(content=_INVALID_JSON), _make_result()])
    await _run(client)

    assert len(user_prompts) == 2
    # Attempt 1: original prompt, no prefix.
    assert "上次" not in user_prompts[0]
    # Attempt 2: corrective prefix added.
    assert "JSON" in user_prompts[1] or "json" in user_prompts[1].lower()
    assert "上次" in user_prompts[1]


# ---------------------------------------------------------------------------
# Test 7: log row fields are fully populated
# ---------------------------------------------------------------------------


async def test_log_row_fields_populated() -> None:
    """Log rows contain prompt, response, tokens, cost, latency, finish_reason."""
    result = _make_result(
        prompt_tokens=200,
        response_tokens=80,
        cached_tokens=50,
        cost_usd=0.0042,
        latency_ms=350,
        finish_reason="stop",
    )
    client = FakeDeepSeekClient([result])
    _, rows = await _run(client)

    row = rows[0]
    assert row.prompt  # non-empty
    assert row.response  # non-empty (the JSON content)
    assert row.prompt_tokens == 200
    assert row.response_tokens == 80
    assert row.cached_tokens == 50
    assert abs(row.cost_usd - 0.0042) < 1e-9
    assert row.latency_ms == 350
    assert row.finish_reason == "stop"
    assert row.tick_id == 1
    assert row.character_id == "char_001"
    assert row.model == "deepseek-v4-pro"
    assert row.provider == "deepseek"
    assert row.created_at is not None


# ---------------------------------------------------------------------------
# Test 8: action character_id and tick_id come from trusted args
# ---------------------------------------------------------------------------


async def test_action_character_id_tick_id_trusted_args() -> None:
    """LLM content with wrong character_id/tick_id is overridden by caller args."""
    # JSON with forged identity fields.
    forged_json = (
        '{"action_type": "THINK", "content": "hello", "mood": "calm", '
        '"inner_thought": "", "triggers_interaction": false, '
        '"character_id": "evil_forgery", "tick_id": 9999}'
    )
    client = FakeDeepSeekClient([_make_result(content=forged_json)])
    action, _ = await _run(client, character_id="char_001", tick_id=5)

    assert action.character_id == "char_001"
    assert action.tick_id == 5


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


async def test_fallback_action_uses_trusted_ids() -> None:
    """Even the fallback DO_NOTHING action uses caller-supplied ids."""
    client = FakeDeepSeekClient([_make_result(content=_INVALID_JSON)] * 3)
    action, _ = await _run(client, character_id="char_xyz", tick_id=42, max_attempts=3)

    assert action.character_id == "char_xyz"
    assert action.tick_id == 42


async def test_single_attempt_only() -> None:
    """max_attempts=1 → one call, if it fails → immediate fallback."""
    client = FakeDeepSeekClient([_make_result(content=_INVALID_JSON)])
    action, rows = await _run(client, max_attempts=1)

    assert action.action_type == ActionType.DO_NOTHING
    # 1 failed row + 1 synthetic fallback row.
    assert len(rows) == 2


async def test_connection_error_logged_and_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """APIConnectionError triggers inner tenacity retry; outer attempt logs error."""
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _seconds: None)

    import httpx as _httpx

    _req = _httpx.Request("POST", "https://api.deepseek.com")
    conn_error = APIConnectionError(request=_req)

    scripts: list[LLMResult | BaseException] = [conn_error] * 5 + [_make_result()]
    client = FakeDeepSeekClient(scripts)
    action, rows = await _run(client)

    assert action.action_type == ActionType.THINK
    assert len(rows) == 2
    assert rows[0].error is not None
    assert rows[1].error is None


async def test_log_rows_have_unique_ids() -> None:
    """Each log row has a distinct UUID id."""
    client = FakeDeepSeekClient([_make_result(content=_INVALID_JSON), _make_result()])
    _, rows = await _run(client)

    ids = [row.id for row in rows]
    assert len(ids) == len(set(ids))
