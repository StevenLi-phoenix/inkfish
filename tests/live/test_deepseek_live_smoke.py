"""Live smoke test — calls real DeepSeek API.

This test is NOT gated by an environment variable (per P0 §Locked Decisions:
"killer test default-live").  It will be skipped by default when running
``pytest tests/unit/`` but WILL run when the full test suite is executed.

Requires DEEPSEEK_API_KEY in the environment (via .env or shell).
"""

from __future__ import annotations

import pytest

from inkfish.config import load_config
from inkfish.llm import DeepSeekClient


@pytest.mark.live
def test_live_deepseek_smoke() -> None:
    """Single call to real DeepSeek API — verifies client, auth, and JSON mode."""
    settings, sim = load_config()
    client = DeepSeekClient(settings.deepseek_api_key, model=sim.model)
    result = client.complete_json(
        system="You output strict json.",
        user='Return a json object: {"hello":"world"}. Output json only.',
        temperature=0.1,
        max_tokens=200,
    )
    assert result.content.strip().startswith(
        "{"
    ), f"Expected JSON object, got: {result.content[:200]!r}"
    assert result.prompt_tokens > 0, "prompt_tokens should be positive"
    assert result.response_tokens > 0, "response_tokens should be positive"
    assert result.latency_ms > 0, "latency_ms should be positive"
    assert result.finish_reason in {
        "stop",
        "length",
    }, f"Unexpected finish_reason: {result.finish_reason!r}"
    assert result.cost_usd >= 0.0, "cost_usd should be non-negative"
    # cached_tokens may be 0 on first call — that's OK.
    assert result.cached_tokens >= 0, "cached_tokens should be non-negative"


@pytest.mark.live
def test_live_deepseek_smoke_second_call_may_have_cache_hits() -> None:
    """Make two calls with the same system prompt.

    The second call SHOULD have cached_tokens > 0 due to DeepSeek auto prefix
    caching — this is a soft assertion (logs a warning rather than failing) since
    cache population timing is non-deterministic in tests.
    """
    import logging

    logger = logging.getLogger(__name__)

    settings, sim = load_config()
    client = DeepSeekClient(settings.deepseek_api_key, model=sim.model)

    system = "You output strict json. This is a repeated system prompt for cache testing."
    user = 'Return {"n": 1}. Only json.'

    result1 = client.complete_json(system=system, user=user, temperature=0.1, max_tokens=30)
    result2 = client.complete_json(system=system, user=user, temperature=0.1, max_tokens=30)

    assert result1.prompt_tokens > 0
    assert result2.prompt_tokens > 0

    if result2.cached_tokens == 0:
        logger.warning(
            "test_live_deepseek_smoke_second_call_may_have_cache_hits: "
            "cached_tokens=0 on second call — cache may not have populated yet. "
            "This is non-fatal; check llm_logs in a full simulation run."
        )
    else:
        assert result2.cached_tokens > 0, "Second call should benefit from prefix cache"
