"""Helpers for picking a sensible completion-token budget per model.

Reasoning-style models (OpenAI o-series, the GPT-5 family, Claude 3.7 / 4.x,
Gemini 2.5 / 3, DeepSeek-R1) can spend their entire output budget on
internal reasoning tokens before emitting any visible content. When that
happens the call either returns an empty completion with
``finish_reason='length'`` (which the agent then logs as
``Invalid response (response without tool call detected)``) or, on some
gateways, surfaces as an HTTP 400 ``invalid_request_error`` with the
message ``Could not finish the message because max_tokens or model output
limit was reached``.

The default 2048 cap baked into TravelGym is fine for non-reasoning models,
but far too small for reasoning models. These helpers route the chat
completion call to ``max_completion_tokens`` (the parameter OpenAI reasoning
models require) with a generous cap, while leaving non-reasoning callers
untouched. Bedrock and Gemini callers should plug ``completion_token_cap``
directly into their provider-specific knob (``inferenceConfig.maxTokens`` and
``max_output_tokens`` respectively) -- see ``UserBench/eval.py`` for the
per-provider wiring.

CANONICAL SOURCE: ``egi_bench/reasoning_models.py`` at the repo root holds
the master copy of these patterns. UserBench is its own venv (no egi_bench
install), so we keep a self-contained mirror here. When you add a model
family, please update both files together. The maintainer runbook lives
at ``docs/reasoning-models.md``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

DEFAULT_CAP = 2048
REASONING_CAP = 16384

# OpenAI reasoning families. The split-on-``/`` handles routed names like
# ``openai/o3-mini`` that some gateways use.
_OPENAI_REASONING_PATTERNS = (
    r"^o[134](?:[-_.]|$)",
    r"^gpt-5(?:[-_.]|$)",
)

# Anthropic reasoning families. Match the family token regardless of where it
# falls in routed names like ``anthropic.claude-sonnet-4-20250514-v1:0``.
# Order doesn't matter here -- we ``re.search`` each pattern.
_CLAUDE_REASONING_PATTERNS = (
    r"claude-3-7(?:[-_.]|$)",
    r"claude-sonnet-4(?:[-_.]|$)",
    r"claude-opus-4(?:[-_.]|$)",
    r"claude-haiku-4(?:[-_.]|$)",
    r"claude-4(?:[-_.]|$)",
)

# Gemini reasoning families. Note the literal ``.`` in ``gemini-2.5``; some
# gateways lower-case to ``gemini-2-5`` so we accept both shapes.
_GEMINI_REASONING_PATTERNS = (
    r"gemini-2[._-]5(?:[-_.]|$)",
    r"gemini-3(?:[-_.]|$)",
)

# Other long-context reasoning models that don't fit the OpenAI / Claude /
# Gemini families above but burn their output budget on hidden reasoning
# tokens just the same. Mirrors ``egi_bench/reasoning_models.py`` (canonical).
_OTHER_REASONING_EXACT = {
    "deepseek-r1",
}


def _normalize(model_name: Optional[str]) -> str:
    if not model_name:
        return ""
    # Strip provider routing prefix (``openai/``, ``anthropic/``, etc.) for
    # the OpenAI patterns, but keep the full lowercased name available for
    # Claude/Gemini matching since their family tokens can appear after a
    # dotted vendor prefix (e.g. ``anthropic.claude-sonnet-4-...``).
    return model_name.lower()


def _matches_any(name: str, patterns) -> bool:
    return any(re.search(p, name) for p in patterns)


def is_openai_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for OpenAI reasoning models (o1/o3/o4 + gpt-5*)."""
    name = _normalize(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return _matches_any(tail, _OPENAI_REASONING_PATTERNS)


def is_claude_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Claude reasoning models (3.7 family, 4.x family)."""
    name = _normalize(model_name)
    if not name:
        return False
    return _matches_any(name, _CLAUDE_REASONING_PATTERNS)


def is_gemini_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Gemini reasoning models (2.5 family, 3.x family)."""
    name = _normalize(model_name)
    if not name:
        return False
    return _matches_any(name, _GEMINI_REASONING_PATTERNS)


def is_other_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for other named reasoning models (e.g. deepseek-r1).

    Provider-routed names are tolerated, so both ``deepseek-r1`` and
    ``together_ai/deepseek-ai/DeepSeek-R1`` qualify.
    """
    name = _normalize(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return name in _OTHER_REASONING_EXACT or tail in _OTHER_REASONING_EXACT


def is_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True when ``model_name`` looks like any provider's reasoning model."""
    return (
        is_openai_reasoning_model(model_name)
        or is_claude_reasoning_model(model_name)
        or is_gemini_reasoning_model(model_name)
        or is_other_reasoning_model(model_name)
    )


def completion_token_cap(
    model_name: Optional[str],
    default_cap: int = DEFAULT_CAP,
    reasoning_cap: int = REASONING_CAP,
) -> int:
    """Pick a token cap that leaves room for hidden reasoning tokens.

    Use this directly to populate provider-specific output caps:
    Bedrock ``inferenceConfig.maxTokens`` and Gemini ``max_output_tokens``.
    For OpenAI-compat ``chat.completions.create`` callers, use
    :func:`chat_completion_token_kwargs` instead -- it also picks the right
    parameter name (``max_completion_tokens`` for reasoning models).
    """
    if is_reasoning_model(model_name):
        return max(default_cap, reasoning_cap)
    return default_cap


def chat_completion_token_kwargs(
    model_name: Optional[str],
    default_cap: int = DEFAULT_CAP,
    reasoning_cap: int = REASONING_CAP,
) -> Dict[str, Any]:
    """Return the right ``max_*_tokens`` kwarg for ``client.chat.completions.create``.

    OpenAI reasoning models only accept ``max_completion_tokens``; older Chat
    Completions deployments only accept ``max_tokens``. Newer OpenAI servers
    accept both, but ``max_completion_tokens`` is the forward-compatible
    name. Callers that need to support very old SDKs/servers should still
    catch ``TypeError`` and retry with ``max_tokens`` set to the same value.

    Non-OpenAI reasoning models (Claude / Gemini) keep ``max_tokens`` here
    because they speak their own native parameter on the provider side; this
    helper is OpenAI-compat-only.
    """
    cap = completion_token_cap(model_name, default_cap, reasoning_cap)
    if is_openai_reasoning_model(model_name):
        return {"max_completion_tokens": cap}
    return {"max_tokens": cap}
