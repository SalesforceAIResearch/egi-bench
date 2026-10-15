# MCPEval - MCP Tool-Use Evaluation

Evaluation framework for assessing LLM performance on MCP (Model Context Protocol) tool-use tasks. Based on [MCPEval](https://arxiv.org/abs/2507.12806).

This integration includes **evaluation only** (no data generation). Pre-verified evaluation tasks are provided for three domains:

- **Airbnb** — property search and booking tasks
- **YFinance** — financial data retrieval tasks
- **National Parks** — park information lookup tasks

## Running via egi-bench (recommended)

MCPEval is registered as a benchmark in the [EGI-Bench](../README.md) suite.
From the repository root, after [`egi-bench setup`](../README.md#5-install-benchmark-environments)
provisions `MCPEval/.venv` and the [local LiteLLM proxy is running](../README.md#4-start-the-local-litellm-proxy):

```bash
# Quick mode: airbnb only (no API keys required), 50 tasks, max 20 turns
egi-bench run --model gpt-4o-mini --mode quick --benchmarks mcpeval

# Deep mode: airbnb + yfinance + national_parks
# (national_parks needs NPS_API_KEY; if unset, the domain is skipped with a note)
egi-bench run --model gpt-4o-mini --mode deep --benchmarks mcpeval
```

Per-mode domain list, `num_tasks`, and `max_turns` live in
[`benchmark_config.yaml`](../benchmark_config.yaml) under `benchmarks.mcpeval`.

The unified runner does both phases automatically: (1) running the model
against the domain's MCP server via `eval.py`, then (2) running MCPEval's
static-tool evaluator (strict + flexible matching). See
[`docs/benchmarks.md`](../docs/benchmarks.md#mcpeval) for the scoring details.

## Standalone Setup

Use these steps only when developing MCPEval in isolation; `egi-bench setup`
already runs the `uv venv` + `uv pip install` pair for you.

```bash
cd MCPEval
uv venv
uv pip install -r requirements.txt
```

### Prerequisites

- **Node.js 20+**: Required for airbnb (`@openbnb/mcp-server-airbnb`) and national_parks (`mcp-server-nationalparks`) MCP servers. The MCP server dependencies require the `File` API which was added in Node.js v20. Earlier versions (v18.x or older) will fail with `ReferenceError: File is not defined`.
- **NPS_API_KEY**: Required for the `national_parks` domain — get a free key from the [NPS Developer Portal](https://www.nps.gov/subjects/developer/api-documentation.htm). Place it in the repo-root `.env`; the egi-bench runner forwards it to the MCP server. (Under egi-bench, `national_parks` is gated via `benchmarks.mcpeval.optional_domains` in `benchmark_config.yaml` — a missing key skips the domain with a note instead of failing the run. For direct standalone `eval.py` invocations the key is required.)

## Usage

### Direct evaluation

```bash
# Airbnb (5 tasks, quick test)
uv run python eval.py --domain airbnb \
    --model-config benchmarks/airbnb/eval_models/gpt-5-nano.json \
    --num-tasks 5 --max-turns 10

# YFinance
uv run python eval.py --domain yfinance \
    --model-config benchmarks/yfinance/eval_models/gpt-5-nano.json \
    --num-tasks 5 --max-turns 10

# National Parks (requires NPS_API_KEY)
export NPS_API_KEY=your-key-here
uv run python eval.py --domain national_parks \
    --model-config benchmarks/national_parks/eval_models/gpt-5-nano.json \
    --num-tasks 5 --max-turns 10
```

### With the local LiteLLM proxy

Ensure the LiteLLM proxy is running on `http://localhost:8008/v1` (see
[`../litellm_proxy/README.md`](../litellm_proxy/README.md)). The wrapper
script retains its legacy filename:

```bash
# Uses default: airbnb domain, gpt-5-nano, 5 tasks
uv run python run_eval_litellm.py

# Custom domain
uv run python run_eval_litellm.py --domain yfinance \
    --model-config benchmarks/yfinance/eval_models/gpt-5-nano.json \
    --num-tasks 5
```

### Arguments

| Argument         | Default                                  | Description                               |
| ---------------- | ---------------------------------------- | ----------------------------------------- |
| `--domain`       | (required)                               | `airbnb`, `yfinance`, or `national_parks` |
| `--model-config` | (required)                               | Path to model config JSON                 |
| `--num-tasks`    | `-1` (all)                               | Number of tasks to evaluate               |
| `--max-turns`    | `30`                                     | Max conversation turns per task           |
| `--output`       | `results/<domain>_<model>_results.jsonl` | Output file path                          |
| `--prompt-file`  | domain default                           | Override system prompt                    |

## File Structure

```
MCPEval/
├── mcpeval/                   # Core evaluation package
│   ├── commons/types.py       # Task, ToolCall, Message models
│   ├── client/                # MCP client (server connections)
│   ├── eval/task_executor.py  # Multi-turn LLM task executor
│   ├── models/llms.py         # OpenAI API wrapper
│   ├── metrics/               # Tool-call matching metrics
│   ├── synthesis/utils.py     # Task loading from JSONL
│   └── utils/cli.py           # Logging and utility functions
├── data/                      # Evaluation task files (JSONL)
├── mcp_servers/yfinance/      # YFinance MCP server
├── benchmarks/                # Per-domain configs and prompts
├── eval.py                    # Main evaluation entry point
├── run_eval_litellm.py     # LiteLLM-proxy wrapper
└── requirements.txt
```

## Evaluation Pipeline

1. Tasks are loaded from `evaluation_tasks_verified.jsonl` (pre-generated and verified)
2. An MCP server is started for the domain (via stdio/npx)
3. For each task, the LLM engages in a multi-turn conversation using available tools
4. Results (tool calls, conversation, success/failure) are saved incrementally to JSONL
5. Resume support: already-evaluated task IDs are skipped on re-run

## Citation

```bibtex
@article{mcpeval2025,
    title={MCPEval: A Benchmark for MCP Tool-Use Evaluation},
    year={2025},
    eprint={2507.12806},
    archivePrefix={arXiv}
}
```
