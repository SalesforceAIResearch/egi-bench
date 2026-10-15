# Benchmark Details

The preferred entry point is the root CLI:

```bash
egi-bench run --model gpt-4o-mini --mode quick
```

Use standalone benchmark commands only when developing or debugging one benchmark.

## CRMArena

```bash
cd CRMArena
.venv/bin/python -u run_tasks.py \
  --model gpt-4o-mini \
  --task_category knowledge_qa \
  --agent_eval_mode aided \
  --agent_strategy tool_call \
  --llm_provider openai \
  --org_type original \
  --base_url http://localhost:8008/v1
```

## HERB

```bash
cd HERB/code
../.venv/bin/python rag.py --model gpt-4o-mini
```

HERB embedding defaults live in `benchmark_config.yaml`.

## PersonaBench

```bash
cd PersonaBench
.venv/bin/python run_eval_litellm.py --model gpt-4o-mini
```

macOS may use `requirements-macos.txt` during setup.

## UserBench

```bash
cd UserBench
.venv/bin/python eval.py --model gpt-4o-mini --envs travel22 travel33 travel44
```

## MCP-Universe

The unified runner drives MCP-Universe's native `BenchmarkRunner` through
`scripts/run_mcpuniverse.py`, with the LLM patched to the local LiteLLM
proxy. Each run invocation handles one domain at a time.

Mode selection lives entirely in `benchmark_config.yaml` under
`benchmarks.mcpuniverse.modes.{quick,deep}` — which domains run, how many
tasks per domain, and the sampling seed. Edit that file to customize.

### Quick mode

Only `financial_analysis` (yfinance + calculator). Chosen because it is the
only MCP-Universe native domain whose MCP servers require **no API keys** —
a stock clone can run it without provisioning SerpAPI / Google Maps / etc.

### Deep mode

Adds `web_search` (needs `SERP_API_KEY`) and `location_navigation` (needs
`GOOGLE_MAPS_API_KEY`). Missing credentials auto-skip the affected domain
with a note in the report rather than failing the run (see
`optional_domains` in `benchmark_config.yaml`).

### Standalone invocation

```bash
# Single domain, capped tasks — useful when debugging one domain.
MCP-Universe/.venv/bin/python scripts/run_mcpuniverse.py financial_analysis --max-tasks 5
```

Domain-to-server and per-domain credential details are documented in
[Deep mode](deep-mode.md).

## MCPEval

The unified runner drives MCPEval in two phases per domain:

1. **`eval.py`** runs the model through that domain's tasks against the domain's MCP stdio server, writing `benchmarks/<domain>/results/unified_<model>_evaluation.jsonl`.
2. **Static tool evaluator** (MCPEval's `evaluate_tool_calls_with_both_match_types`) diffs the predictions against `data/<domain>/evaluation_tasks_verified.jsonl` using both strict and flexible matching, writing `..._analysis.json`.

`score_mcpeval` then reports **flexible `average_score`** as the per-domain score (0-100, continuous). Strict and flexible success rates plus per-component (tool-name / parameter / order) accuracies are preserved in `raw_metrics` for diagnosis.

Mode profiles live in `benchmark_config.yaml` under `benchmarks.mcpeval.modes`:

| Mode | Domains | Notes |
| --- | --- | --- |
| quick | `airbnb` | Multi-step tool sequencing, no API keys. ~40 min at gpt-4.1 via the local LiteLLM proxy. |
| deep | `airbnb`, `yfinance`, `national_parks` | Adds yfinance (no extra keys) and national_parks (`NPS_API_KEY` required). |

### Standalone invocation

```bash
cd MCPEval
.venv/bin/python -u eval.py \
  --domain airbnb \
  --model-config benchmarks/airbnb/eval_models/unified_gpt-4.1.json \
  --num-tasks 50 --max-turns 20 \
  --output benchmarks/airbnb/results/unified_gpt-4.1_evaluation.jsonl

.venv/bin/python -c "
from mcpeval.metrics.static_tool_eval import evaluate_tool_calls_with_both_match_types
evaluate_tool_calls_with_both_match_types(
    'data/airbnb/evaluation_tasks_verified.jsonl',
    'benchmarks/airbnb/results/unified_gpt-4.1_evaluation.jsonl',
    'benchmarks/airbnb/results/unified_gpt-4.1_analysis.json',
)
"
```

The unified runner does both steps automatically.

## Benchforce

```bash
cd Benchforce
.venv/bin/python run_benchforce.py \
  --environment hospital \
  --model gpt-4o-mini \
  --base-url http://localhost:8008/v1
```

## LoCoBench

```bash
cd LoCoBench
.venv/bin/python run_eval_litellm.py --model gpt-4o-mini --difficulty easy
```
