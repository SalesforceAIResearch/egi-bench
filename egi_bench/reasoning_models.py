"""Reasoning-model detection + token-budget helpers.

This is the **canonical** source of truth for "is this model a long-context
reasoning model that needs a bumped output-token budget?" used across all
EGI-Bench wrappers / adapters.

Why one shared module:
    Reasoning-style models (OpenAI o-series + the GPT-5 family, Gemini 2.5/3,
    Claude 3.7 + 4.x, DeepSeek-R1, ...) can spend their entire output budget
    on internal reasoning tokens before emitting any visible content. When
    that happens the call either returns an empty completion (which the
    agent then logs as "Invalid action" / "no tool call detected") or
    surfaces as an HTTP 400 ``invalid_request_error`` with the message
    "Could not finish the message because max_tokens or model output limit
    was reached". Every benchmark adapter therefore needs to (a) detect
    such models and (b) bump the per-call output cap before issuing the
    request. Keeping the regex tables here avoids drift between adapters.

Where this module is consumed:
    * ``run_all.py`` (egi-bench's main runner venv) — direct import. Used
      to size the ``max_tokens`` value baked into the per-domain MCPEval
      ``model_config`` JSON.
    * ``scripts/run_mcpuniverse.py`` (runs under MCP-Universe's venv) —
      imported via a ``sys.path.insert(REPO_ROOT)`` hack since this module
      is pure stdlib (``re``-only) and works from any Python 3.10+ env.
    * Mirrored copies (kept in sync by hand, see header notes there):
        - ``CRMArena/crm_sandbox/agents/utils.py`` — used by
          ``ToolCallAgent`` / ``ChatAgent`` to size their LiteLLM caps.
        - ``UserBench/travelgym/_token_utils.py`` — used by
          ``UserBench/eval.py`` to set provider-specific output caps
          (Bedrock ``inferenceConfig.maxTokens``, Gemini
          ``max_output_tokens``, OpenAI ``max_completion_tokens``).

If you add a new model family to the patterns below, please mirror the
addition in the two files listed above so all benchmarks pick it up.

See ``docs/reasoning-models.md`` for the maintainer-facing runbook
("when to add a model, how to pick regex vs exact, how to test").
"""

from __future__ import annotations

import re
from typing import Optional

# OpenAI reasoning families. Use a prefix check on the gpt-5 side so future
# point releases (gpt-5.4, gpt-5.5-mini, gpt-5.4-nano, ...) auto-qualify
# without code changes. The ``[134]`` covers o1/o3/o4 today; bump if a new
# o-series number ships.
_OPENAI_REASONING_PATTERNS = (
    r"^o[134](?:[-_.]|$)",
    r"^o1(?:[-_.]|$)",
    r"^gpt-5(?:[-_.]|$)",
)

# Gemini reasoning families. Note the literal ``.`` in ``gemini-2.5``; some
# gateways lower-case to ``gemini-2-5`` so we accept both shapes. Excludes
# Gemini 2.0 / 1.5, which are not thinking models.
_GEMINI_REASONING_PATTERNS = (
    r"gemini-2[._-]5(?:[-_.]|$)",
    r"gemini-3(?:[-_.]|$)",
)

# Anthropic reasoning families (Claude 3.7 + Claude 4.x). Extended thinking
# is opt-in for Claude (callers must pass ``thinking={"type":"enabled",...}``).
# We still classify these as reasoning because:
# (1) MCP-Universe's claude_wr / claude_gateway / sf_research adapters do
#     enable Claude thinking and need the bumped cap, and
# (2) the bumped budget is harmless when thinking is off — the model just
#     doesn't use the headroom.
# Patterns match the family token regardless of where it falls in routed
# names like ``anthropic.claude-sonnet-4-20250929-v1:0`` or
# ``bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0``.
_CLAUDE_REASONING_PATTERNS = (
    r"claude-3-7(?:[-_.]|$)",
    r"claude-sonnet-4(?:[-_.]|$)",
    r"claude-opus-4(?:[-_.]|$)",
    r"claude-haiku-4(?:[-_.]|$)",
    r"claude-4(?:[-_.]|$)",
)

# Other long-context reasoning models that don't fit the OpenAI / Gemini /
# Claude families above but burn their output budget on hidden reasoning
# tokens just the same.
_OTHER_REASONING_EXACT = {
    "deepseek-r1",
}

# Default reasoning-cap values used by the helper functions below. Picked to
# leave plenty of room for an extended-thinking pass plus the visible reply
# (Gemini 2.5 Pro for example will happily eat 30k+ tokens of internal
# thought on multi-step ReAct tasks). Callers are free to override.
DEFAULT_REASONING_MAX_TOKENS = 50000


def _normalize_model_name(model_name: Optional[str]) -> str:
    if not model_name:
        return ""
    return model_name.lower()


def _matches_any(name: str, patterns) -> bool:
    return any(re.search(p, name) for p in patterns)


def is_openai_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for OpenAI reasoning models (o1/o3/o4 + gpt-5*).

    Tolerates routing prefixes like ``openai/o1-mini`` or ``sfr/gpt-5``.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return _matches_any(tail, _OPENAI_REASONING_PATTERNS)


def is_gemini_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Gemini reasoning models (2.5 family, 3.x family).

    Matches every variant exposed by the LiteLLM proxy:
    ``gemini-2.5-flash``, ``gemini-2.5-pro``, ``vertex/gemini-2.5-*``,
    ``vertex_ai/gemini-2.5-*``, ``gemini/gemini-2.5-*``,
    ``express/gemini-2.5-*``, plus the dated previews
    (``gemini-2.5-flash-preview-04-17``, ``gemini-2.5-pro-preview-03-25``).
    Returns False for ``gemini-2.0-flash`` / ``gemini-1.5-pro``.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    return _matches_any(name, _GEMINI_REASONING_PATTERNS)


def is_claude_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for Claude reasoning models (3.7 family, 4.x family).

    Matches the family token wherever it appears in the routed name, so all
    of ``claude-sonnet-4-5``, ``claude-opus-4-5``,
    ``bedrock/claude-3-7-sonnet``, ``bedrock/us.anthropic.claude-opus-4-...``,
    ``express/claude-sonnet-4-6``, etc. qualify. Returns False for Claude
    3.5 and earlier, which don't support extended thinking.
    """
    name = _normalize_model_name(model_name)
    if not name:
        return False
    return _matches_any(name, _CLAUDE_REASONING_PATTERNS)


def is_long_context_reasoning_model(model_name: Optional[str]) -> bool:
    """Return True for any model that needs a bumped output-token budget.

    Callers should pick :data:`DEFAULT_REASONING_MAX_TOKENS` (or larger)
    when this returns True, and their normal small default otherwise.
    """
    if (
        is_openai_reasoning_model(model_name)
        or is_gemini_reasoning_model(model_name)
        or is_claude_reasoning_model(model_name)
    ):
        return True
    name = _normalize_model_name(model_name)
    if not name:
        return False
    tail = name.split("/")[-1]
    return name in _OTHER_REASONING_EXACT or tail in _OTHER_REASONING_EXACT


def reasoning_max_tokens(
    model_name: Optional[str],
    default: int,
    reasoning_cap: int = DEFAULT_REASONING_MAX_TOKENS,
) -> int:
    """Pick an output-token cap that leaves room for hidden reasoning tokens.

    Returns ``reasoning_cap`` for any model that
    :func:`is_long_context_reasoning_model` recognizes, else ``default``.
    """
    if is_long_context_reasoning_model(model_name):
        return max(default, reasoning_cap)
    return default
