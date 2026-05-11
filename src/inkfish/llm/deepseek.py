"""inkfish.llm.deepseek — Thin OpenAI-SDK wrapper pointed at DeepSeek.

This module is NOT retry-aware: it makes exactly one HTTP call and raises any
openai exception to the caller.  Retry logic and JSON repair live in retry.py.

Caching note: DeepSeek auto prefix caching returns cache hit information in one
of two ways depending on the API revision:
  - Modern path: ``response.usage.prompt_tokens_details.cached_tokens``
  - Legacy path: ``response.usage.model_extra["prompt_cache_hit_tokens"]``
Both paths are tried defensively; 0 is returned if neither is present.
"""

from __future__ import annotations

import logging
import time
from typing import NamedTuple

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import SecretStr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing table (USD per million tokens) — deepseek-v4-pro has a 75% discount
# through 2026-05-31, so multiply published rates by 0.25.
# ---------------------------------------------------------------------------
_PRICING_USD_PER_M: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {
        "input": 0.30 * 0.25,         # $0.075 / M
        "output": 0.50 * 0.25,         # $0.125 / M
        "cached_input": 0.03 * 0.25,   # $0.0075 / M (cache hits are 1/10 of input)
    },
    "deepseek-v4-flash": {
        "input": 0.30,
        "output": 0.50,
        "cached_input": 0.03,
    },
}

# Fallback rates for unknown model names (assume non-discounted v4-flash pricing).
_DEFAULT_PRICING: dict[str, float] = _PRICING_USD_PER_M["deepseek-v4-flash"]


class LLMResult(NamedTuple):
    """Immutable result of a single LLM completion call.

    Fields:
        content:         Raw text content from the model.
        prompt_tokens:   Total prompt tokens billed (includes cached).
        response_tokens: Completion tokens billed.
        cached_tokens:   Prompt tokens that were served from the prefix cache.
        cost_usd:        Estimated call cost in USD.
        latency_ms:      Wall-clock call duration in milliseconds.
        finish_reason:   ``"stop"`` | ``"length"`` | ``"content_filter"`` | etc.
    """

    content: str
    prompt_tokens: int
    response_tokens: int
    cached_tokens: int
    cost_usd: float
    latency_ms: int
    finish_reason: str


def _extract_cached_tokens(completion: ChatCompletion) -> int:
    """Return cached token count from a completion response.

    Tries two paths:
    1. ``usage.prompt_tokens_details.cached_tokens`` — modern SDK / OpenAI spec.
    2. ``usage.model_extra["prompt_cache_hit_tokens"]`` — DeepSeek legacy field.
    Returns 0 if neither is present (or if usage itself is absent).
    """
    if completion.usage is None:
        return 0

    # Path 1: standard prompt_tokens_details.cached_tokens
    details = completion.usage.prompt_tokens_details
    if details is not None and details.cached_tokens is not None:
        return details.cached_tokens

    # Path 2: legacy DeepSeek model_extra field
    extra = completion.usage.model_extra
    if extra and "prompt_cache_hit_tokens" in extra:
        val = extra["prompt_cache_hit_tokens"]
        if isinstance(val, int):
            return val

    return 0


def _compute_cost(
    model: str,
    prompt_tokens: int,
    response_tokens: int,
    cached_tokens: int,
) -> float:
    """Compute estimated USD cost for one completion call.

    Formula:
        cost = (non_cached_prompt * input_rate
                + cached_prompt * cached_input_rate
                + response * output_rate) / 1_000_000

    All rates are per million tokens.
    """
    rates = _PRICING_USD_PER_M.get(model, _DEFAULT_PRICING)
    non_cached = max(0, prompt_tokens - cached_tokens)
    cost = (
        non_cached * rates["input"]
        + cached_tokens * rates["cached_input"]
        + response_tokens * rates["output"]
    ) / 1_000_000
    return cost


class DeepSeekClient:
    """Thin wrapper around the OpenAI SDK pointed at ``https://api.deepseek.com``.

    All calls use JSON mode (``response_format={"type": "json_object"}``).
    The caller is responsible for including the word "json" somewhere in the
    user prompt so DeepSeek's JSON mode activates correctly.

    This class does NOT retry.  Transient errors (429, connection errors,
    timeouts) are propagated directly to the caller; use ``call_with_retry``
    from ``retry.py`` for production use.
    """

    def __init__(
        self,
        api_key: SecretStr,
        model: str = "deepseek-v4-pro",
        *,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key.get_secret_value(),
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # tenacity handles retries, not the SDK
        )
        self.model = model
        self.base_url = base_url

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
    ) -> LLMResult:
        """Make a single JSON-mode chat completion call.

        Parameters:
            system:      System prompt text.
            user:        User prompt text.  MUST contain the word "json" so that
                         DeepSeek's ``json_object`` mode activates.
            temperature: Sampling temperature.
            max_tokens:  Maximum completion tokens.

        Returns:
            ``LLMResult`` with content, token counts, cost, latency.

        Raises:
            openai.RateLimitError:     HTTP 429 rate limit.
            openai.APIConnectionError: Network / DNS error.
            openai.APITimeoutError:    Call exceeded *timeout* seconds.
            openai.APIStatusError:     Any other non-2xx response.
        """
        t0 = time.monotonic()
        completion: ChatCompletion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        content = completion.choices[0].message.content or ""
        finish_reason = completion.choices[0].finish_reason or "unknown"

        # Handle rare 5xx where usage field is absent.
        if completion.usage is None:
            logger.warning(
                "DeepSeekClient.complete_json: usage absent in response "
                "(model=%s finish_reason=%s) — defaulting token counts to 0",
                self.model,
                finish_reason,
            )
            prompt_tokens = 0
            response_tokens = 0
            cached_tokens = 0
        else:
            prompt_tokens = completion.usage.prompt_tokens
            response_tokens = completion.usage.completion_tokens
            cached_tokens = _extract_cached_tokens(completion)

        cost_usd = _compute_cost(self.model, prompt_tokens, response_tokens, cached_tokens)

        logger.debug(
            "DeepSeekClient.complete_json: model=%s prompt=%d cached=%d "
            "response=%d cost=%.6f latency=%dms finish=%s",
            self.model,
            prompt_tokens,
            cached_tokens,
            response_tokens,
            cost_usd,
            latency_ms,
            finish_reason,
        )

        return LLMResult(
            content=content,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
