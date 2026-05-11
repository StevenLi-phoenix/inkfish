"""Unit tests for inkfish.llm.deepseek.DeepSeekClient.

All HTTP calls are mocked with respx so no real network traffic occurs.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import SecretStr

from inkfish.llm.deepseek import DeepSeekClient, LLMResult, _compute_cost

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_KEY = SecretStr("fake-deepseek-key")
_BASE_URL = "https://api.deepseek.com"
_COMPLETIONS_URL = f"{_BASE_URL}/chat/completions"


def _make_response(
    content: str = '{"action_type": "DO_NOTHING"}',
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
    finish_reason: str = "stop",
    cached_tokens_details: int | None = None,
    cached_tokens_extra: int | None = None,
) -> dict:
    """Build a minimal ChatCompletion response JSON.

    ``cached_tokens_details`` → put in ``prompt_tokens_details.cached_tokens``
    ``cached_tokens_extra``   → put in top-level ``prompt_cache_hit_tokens`` (legacy)
    """
    usage: dict = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cached_tokens_details is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached_tokens_details}
    if cached_tokens_extra is not None:
        usage["prompt_cache_hit_tokens"] = cached_tokens_extra

    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "deepseek-v4-pro",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def _client(model: str = "deepseek-v4-pro") -> DeepSeekClient:
    return DeepSeekClient(_FAKE_KEY, model)


# ---------------------------------------------------------------------------
# Test 1: basic success path
# ---------------------------------------------------------------------------


def test_complete_json_success() -> None:
    """Mock returns a valid JSON string; LLMResult has correct content + tokens."""
    content = '{"action_type": "THINK", "content": "hello"}'
    body = _make_response(content=content, prompt_tokens=100, completion_tokens=50)

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(
            system="You output json.",
            user="Return a json object.",
        )

    assert isinstance(result, LLMResult)
    assert result.content == content
    assert result.prompt_tokens == 100
    assert result.response_tokens == 50
    assert result.finish_reason == "stop"
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Test 2: cached_tokens from prompt_tokens_details.cached_tokens
# ---------------------------------------------------------------------------


def test_complete_json_extracts_cached_tokens_from_details_path() -> None:
    """``prompt_tokens_details.cached_tokens`` → LLMResult.cached_tokens."""
    body = _make_response(
        prompt_tokens=1000,
        completion_tokens=100,
        cached_tokens_details=42,
    )

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.cached_tokens == 42


# ---------------------------------------------------------------------------
# Test 3: cached_tokens from legacy prompt_cache_hit_tokens (model_extra)
# ---------------------------------------------------------------------------


def test_complete_json_extracts_cached_tokens_from_extra_path() -> None:
    """Legacy ``prompt_cache_hit_tokens`` in usage root → LLMResult.cached_tokens."""
    body = _make_response(
        prompt_tokens=1000,
        completion_tokens=100,
        cached_tokens_extra=42,
    )

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.cached_tokens == 42


# ---------------------------------------------------------------------------
# Test 4: no cache info → cached_tokens == 0
# ---------------------------------------------------------------------------


def test_complete_json_no_cached_returns_zero() -> None:
    """Usage with no cache fields → cached_tokens == 0."""
    body = _make_response(prompt_tokens=500, completion_tokens=200)

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.cached_tokens == 0


# ---------------------------------------------------------------------------
# Test 5: cost computation
# ---------------------------------------------------------------------------


def test_complete_json_computes_cost_correctly() -> None:
    """Known token counts → cost_usd matches formula for deepseek-v4-pro (75% off).

    Rates (per M, with 75% discount):
      input        = 0.30 * 0.25 = 0.075
      cached_input = 0.03 * 0.25 = 0.0075
      output       = 0.50 * 0.25 = 0.125

    Given: prompt=1000, cached=200, response=500
      cost = (1000-200)*0.075/1M + 200*0.0075/1M + 500*0.125/1M
           = 800*0.075/1M + 200*0.0075/1M + 500*0.125/1M
           = 0.00006 + 0.0000015 + 0.0000625
           = 0.0001240
    """
    body = _make_response(
        prompt_tokens=1000,
        completion_tokens=500,
        cached_tokens_details=200,
    )

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client("deepseek-v4-pro").complete_json(system="sys", user="return json")

    expected = (800 * 0.075 + 200 * 0.0075 + 500 * 0.125) / 1_000_000
    assert abs(result.cost_usd - expected) < 1e-10


def test_compute_cost_directly() -> None:
    """_compute_cost helper produces correct values independently."""
    cost = _compute_cost("deepseek-v4-pro", 1000, 500, 200)
    expected = (800 * 0.075 + 200 * 0.0075 + 500 * 0.125) / 1_000_000
    assert abs(cost - expected) < 1e-10


# ---------------------------------------------------------------------------
# Test 6: 429 → RateLimitError bubbles up
# ---------------------------------------------------------------------------


def test_complete_json_raises_on_rate_limit() -> None:
    """HTTP 429 should raise openai.RateLimitError to the caller."""
    from openai import RateLimitError

    error_body = {"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}}

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(
            return_value=httpx.Response(429, json=error_body)
        )
        with pytest.raises(RateLimitError):
            _client().complete_json(system="sys", user="return json")


# ---------------------------------------------------------------------------
# Test 7: timeout → APITimeoutError
# ---------------------------------------------------------------------------


def test_complete_json_raises_on_timeout() -> None:
    """Request timeout should raise openai.APITimeoutError."""
    from openai import APITimeoutError

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        with pytest.raises(APITimeoutError):
            _client().complete_json(system="sys", user="return json")


# ---------------------------------------------------------------------------
# Test 8: latency_ms is positive (using side_effect delay)
# ---------------------------------------------------------------------------


def test_latency_ms_is_positive() -> None:
    """DeepSeekClient records a non-zero latency even for near-instant mocked calls."""
    body = _make_response()

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    # Even a mock call takes > 0 ms due to Python overhead.
    assert result.latency_ms >= 0


def test_latency_ms_reflects_actual_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatched time.monotonic simulates a 200ms call → latency_ms >= 200."""
    body = _make_response()

    # Simulate monotonic returning values 0.200 apart.
    _calls: list[float] = [0.0, 0.200]

    def fake_monotonic() -> float:
        return _calls.pop(0)

    monkeypatch.setattr("inkfish.llm.deepseek.time.monotonic", fake_monotonic)

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.latency_ms >= 200


# ---------------------------------------------------------------------------
# Test: finish_reason propagation
# ---------------------------------------------------------------------------


def test_complete_json_finish_reason_length() -> None:
    """finish_reason='length' is propagated into LLMResult."""
    body = _make_response(finish_reason="length")

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.finish_reason == "length"


# ---------------------------------------------------------------------------
# Test: details path takes priority over extra path
# ---------------------------------------------------------------------------


def test_details_path_takes_priority_over_extra_path() -> None:
    """When both paths present, prompt_tokens_details.cached_tokens wins."""
    body = _make_response(
        prompt_tokens=1000,
        completion_tokens=100,
        cached_tokens_details=99,
        cached_tokens_extra=42,  # should be ignored
    )

    with respx.mock:
        respx.post(_COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=body))
        result = _client().complete_json(system="sys", user="return json")

    assert result.cached_tokens == 99
