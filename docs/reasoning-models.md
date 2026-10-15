# Reasoning-Model Registry

EGI-Bench keeps a small registry of model-name patterns that identify
"reasoning" / "thinking" models — the family of LLMs that spend a large
fraction of their per-call output budget on internal reasoning tokens
before emitting any visible content. Examples today: OpenAI o-series
(o1 / o3 / o4) + the GPT-5 family, Gemini 2.5 / 3, Claude 3.7 + Claude
4.x with extended thinking enabled, and DeepSeek-R1.

This page is the **runbook for adding a new reasoning-model family** to
the registry — what to add, where, how to test it, and the design
constraints to respect along the way.

For the *parameter-renaming* story (`max_completion_tokens` vs
`max_tokens`, `drop_params`, etc.) handled at the LiteLLM layer, see
[`docs/llm-providers.md` → "Reasoning-family parameter handling"](./llm-providers.md#reasoning-family-parameter-handling).

## Why the registry exists

When a thinking model receives a small `max_tokens` budget, it can spend
its entire allowance on hidden reasoning tokens and return:

- An empty completion (visible content `None`) with `finish_reason="length"`,
  which the agent loop then logs as `Invalid action` /
  `Invalid response (response without tool call detected)`; or
- An HTTP 400 `invalid_request_error` with the message
  `Could not finish the message because max_tokens or model output limit
  was reached`.

EGI-Bench therefore needs to (a) detect whether a given model name is
"reasoning-class" and (b) pre-bump the per-call output cap before
issuing the request. The registry is the data table that drives (a).

## Where the registry lives

The **canonical source of truth** is one pure-stdlib module at the repo
root:

```text
egi_bench/reasoning_models.py
```

It's pure stdlib (`re` only) so it loads under any Python 3.10+ venv.
Two adapters import it directly:

| Caller | How it imports the canonical helper |
|---|---|
| `run_all.py` (egi-bench's main runner venv) | direct `from egi_bench.reasoning_models import …`; uses the helpers when writing the per-domain MCPEval `model_config` JSON. |
| `scripts/run_mcpuniverse.py` (runs under MCP-Universe's venv) | adds `REPO_ROOT` to `sys.path`, then imports the canonical module; uses the helpers when patching the LLM block of each MCP-Universe YAML. |

The remaining adapters can't `import egi_bench` — they each live in
their own isolated `.venv` that does not have the egi-bench package
installed. They keep **mirrored copies** of the patterns instead:

| Mirror | Uses it for |
|---|---|
| [`CRMArena/crm_sandbox/agents/utils.py`](../CRMArena/crm_sandbox/agents/utils.py) | `ToolCallAgent` / `ChatAgent` size their LiteLLM-proxy `max_tokens` from the helpers. |
| [`UserBench/travelgym/_token_utils.py`](../UserBench/travelgym/_token_utils.py) | `UserBench/eval.py` sizes per-provider output caps (Bedrock `inferenceConfig.maxTokens`, Gemini `max_output_tokens`, OpenAI `max_completion_tokens`). |
| [`MCPEval/mcpeval/models/llms.py`](../MCPEval/mcpeval/models/llms.py) | A minimal inline OpenAI-only mirror used to rename `max_tokens` → `max_completion_tokens` for o1/o3/o4/gpt-5* on the OpenAIWrapper path. |

Each mirror carries a header comment pointing back here. **When you add
a model family, update the canonical source and every applicable mirror
together** (see the runbook below).

## When does a model belong in the registry?

Add a model to the registry when **all** of these are true:

1. The model implements a hidden reasoning / thinking pass (CoT,
   chain-of-thought tokens, "thought signatures", etc.) that consumes
   tokens *out of the same per-call output budget* as the visible reply.
2. With the benchmark default cap (typically 2048–4096 tokens), the
   model has reproducibly returned empty content / `finish_reason=length`
   on at least one EGI-Bench task.
3. Bumping the cap to ~50000 tokens (`DEFAULT_REASONING_MAX_TOKENS`)
   resolves the truncation.

If only #1 is true (e.g. a reasoning model that ships a generous
**default** server-side cap), you don't need to register it — adding it
is harmless but bloats the patterns. If #1 is false (the model exposes
a separate "thinking budget" knob, like Claude 3.7's
`thinking={"type":"enabled", "budget_tokens": …}`), prefer wiring up
that knob over registering the family.

> Note on Claude: we register the Claude 3.7 + 4.x families even though
> CRMArena's agents don't explicitly enable extended thinking today.
> The bumped budget is harmless when thinking is off (the model just
> doesn't use the headroom), and other adapters — MCP-Universe's
> claude_wr / claude_gateway / sf_research routes — do enable Claude
> thinking and would otherwise truncate.

## Runbook: add a new reasoning-model family

### 1. Decide regex vs. exact-name

The canonical module exposes two complementary registries:

| Registry | Use when… | Example |
|---|---|---|
| Family **regex pattern** (`_OPENAI_…`, `_GEMINI_…`, `_CLAUDE_…`) | A whole family rolls forward with predictable point releases (`gpt-5.4`, `gpt-5.5-mini`, `claude-sonnet-4-5`, `gemini-2.5-flash-preview-08-12`, `gemini-3.1-pro-preview`, …). The regex matches every current and future variant without code edits. | `r"^gpt-5(?:[-_.]\|$)"` already covers `gpt-5`, `gpt-5-mini`, `gpt-5.4-nano`; `r"gemini-3(?:[-_.]\|$)"` covers `gemini-3`, `gemini-3-pro`, `gemini-3.1-pro-preview`. |
| Exact-name set (`_OTHER_REASONING_EXACT`) | A one-off model that doesn't fit the OpenAI / Gemini / Claude families, or where you want to opt **only one** specific name in. | `"deepseek-r1"` (without `r2`, `r3`, ...). |

### 2. Pick the right anchor for the regex

Look at how routed names appear in
[`litellm_proxy/litellm_config.yaml`](../litellm_proxy/litellm_config.yaml).
Two distinct shapes:

- **Last-segment families** (OpenAI o-series + GPT-5*) always sit as
  the final `/`-separated segment: `openai/o3-mini`, `azure/openai/o3`,
  `litellm_proxy/openai/gpt-5`, `sfr/o1-preview`. Anchor the regex with
  `^…` and match against `name.lower().split("/")[-1]`.
- **In-name families** (Gemini, Claude, DeepSeek) embed their family
  token deep inside routed names: `bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0`,
  `vertex_ai/gemini-2.5-pro`, `express/gemini-3.1-pro-preview`,
  `together_ai/deepseek-ai/DeepSeek-R1`.
  Use `re.search` on the full lowercased name with a trailing
  word-boundary like `(?:[-_.]|$)` so `claude-3-7` doesn't accidentally
  match a hypothetical `claude-3-77`.

The shipped helpers already implement both strategies correctly — see
the docstrings in
[`egi_bench/reasoning_models.py`](../egi_bench/reasoning_models.py).
Add your pattern to whichever registry already uses the matching
strategy you need.

### 3. Apply the change to all four sites

Order matters: change the canonical source first, then the mirrors.

1. **Canonical source** — edit
   [`egi_bench/reasoning_models.py`](../egi_bench/reasoning_models.py).
   Add the pattern to the appropriate constant
   (`_OPENAI_REASONING_PATTERNS`, `_GEMINI_REASONING_PATTERNS`,
   `_CLAUDE_REASONING_PATTERNS`, or `_OTHER_REASONING_EXACT`). Update
   the docstring of the matching `is_*_reasoning_model` helper if the
   prose mentions specific examples.
2. **CRMArena mirror** — edit
   [`CRMArena/crm_sandbox/agents/utils.py`](../CRMArena/crm_sandbox/agents/utils.py)
   in the same way (the constants live near the top of the file).
3. **UserBench mirror** — edit
   [`UserBench/travelgym/_token_utils.py`](../UserBench/travelgym/_token_utils.py).
   This file uses slightly different cap defaults (`DEFAULT_CAP=2048`,
   `REASONING_CAP=16384`) — the patterns are the only thing that needs
   to change.
4. **MCPEval mirror** — only edit
   [`MCPEval/mcpeval/models/llms.py`](../MCPEval/mcpeval/models/llms.py)
   if the new family is an **OpenAI** reasoning model. That file's
   inline mirror only handles the OpenAI param-rename
   (`max_tokens` → `max_completion_tokens`); Gemini / Claude / "other"
   families go through the `run_all.py` JSON-config path and don't
   need a touch here.

### 4. Add a test case

Append your new model name(s) to the canonical-helper smoke test (see
the recipe in the next section) and run it from `egi_bench`'s venv.
Then run the per-mirror smoke commands from the matching benchmark
venvs to confirm parity.

### 5. (Optional) Add LiteLLM Proxy entries

If users will reach the new model under a friendly name through the
local proxy, add a `model_list` entry to
[`litellm_proxy/litellm_config.yaml`](../litellm_proxy/litellm_config.yaml)
following one of the
[provider recipes](./llm-providers.md#provider-recipes). The registry
patterns must match whatever the user passes to `--model`, including
any provider-routing prefix the proxy entry surfaces (e.g. `vertex/`,
`bedrock/`, `express/`).

## Prefix-tolerance design (do not break this)

The registry is exercised against fully-routed model names such as:

- `openai/o3-mini`
- `azure/openai/o3-mini`
- `litellm_proxy/openai/gpt-5`
- `vertex/gemini-2.5-flash`
- `vertex_ai/gemini-2.5-pro`
- `express/gemini-3.1-pro-preview`
- `bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0`
- `together_ai/deepseek-ai/DeepSeek-R1`

Two invariants make this work; please preserve both when extending:

1. **Last-segment matching for OpenAI families.** Using
   `name.lower().split("/")[-1]` lets nested routers like
   `azure/openai/o3-mini` resolve correctly while avoiding false
   positives from substring contamination.
2. **Boundary anchors on every regex.** `gemini-2[._-]5(?:[-_.]|$)`
   refuses to match `gemini-2.55-flash` (a hypothetical future model
   that we'd want to register explicitly). Always include the trailing
   `(?:[-_.]|$)` boundary unless you really do want a prefix-only
   match.

## Smoke-test recipe

Drop the snippet below into a scratch file and run it from the
egi-bench venv after editing the canonical module. The same template
works for the per-mirror checks — substitute the import line for the
mirror's symbols.

```python
from egi_bench.reasoning_models import (
    is_openai_reasoning_model,
    is_gemini_reasoning_model,
    is_claude_reasoning_model,
    is_long_context_reasoning_model,
    reasoning_max_tokens,
    DEFAULT_REASONING_MAX_TOKENS,
)

# Add positive AND negative cases for the new family. Negatives prevent
# accidental over-matching (e.g. a Gemini 2.5 pattern matching 2.55).
cases = [
    ("openai/<your-new-model>", True),
    ("vertex/<your-new-model>", True),
    ("vendor/<adjacent-but-different>", False),
]
for name, want in cases:
    got = is_long_context_reasoning_model(name)
    assert got == want, f"{name!r}: want={want} got={got}"

# Sanity: the chosen cap kicks in.
assert reasoning_max_tokens("<your-new-model>", default=4096) == DEFAULT_REASONING_MAX_TOKENS
print(f"OK: {len(cases)} new cases pass")
```

To validate every venv:

```bash
# Canonical source (egi-bench root venv)
.venv/bin/python <scratch.py>

# CRMArena mirror
CRMArena/.venv/bin/python -c "
from crm_sandbox.agents.utils import is_long_context_reasoning_model as f
assert f('<your-new-model>') is True
"

# UserBench mirror
UserBench/.venv/bin/python -c "
import sys; sys.path.insert(0, 'UserBench')
from travelgym._token_utils import is_reasoning_model as f
assert f('<your-new-model>') is True
"

# MCPEval mirror (only matters for OpenAI reasoning families)
MCPEval/.venv/bin/python -c "
from mcpeval.models.llms import _is_openai_reasoning_model as f
assert f('openai/<your-new-model>') is True
"
```

## Common pitfalls

- **Forgetting a mirror.** The most common drift cause is editing only
  the canonical source. CI does not catch this — keep the mirrors in
  sync by hand and reference the runbook above when reviewing PRs.
- **Anchoring against the full string for OpenAI families.** Patterns
  like `^o3` against `azure/openai/o3-mini` will silently miss because
  `^` matches the *string* start, not the segment. Always split on `/`
  for OpenAI families.
- **Dropping the boundary suffix.** `claude-3-7` (no boundary) will
  also match `claude-3-77`, which Anthropic could legitimately ship.
  Keep `(?:[-_.]|$)`.
- **Bumping `DEFAULT_REASONING_MAX_TOKENS` without re-checking budgets.**
  50000 is generous on purpose — it leaves room for an extended
  thinking pass plus the visible reply on multi-step ReAct tasks. If
  you raise it, also confirm the upstream provider accepts the new
  value (some gateways enforce per-route ceilings).
- **Routing a non-reasoning model through `_OTHER_REASONING_EXACT`.**
  The cap bump is only beneficial for genuine thinking models. Adding
  a regular instruction-tuned model wastes tokens (which most
  benchmarks bill against the user) and provides no quality lift.

## Related references

- [`egi_bench/reasoning_models.py`](../egi_bench/reasoning_models.py) —
  canonical helpers + module docstring with per-pattern rationale.
- [`docs/llm-providers.md`](./llm-providers.md) — LiteLLM Proxy and
  per-provider routing reference; see the "Reasoning-family parameter
  handling" section for the LiteLLM-side parameter renaming story.
- [`docs/troubleshooting.md`](./troubleshooting.md) — symptom catalog
  including "Invalid action" / empty completions, which is what
  usually surfaces when a reasoning model isn't yet registered.
