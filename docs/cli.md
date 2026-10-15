# EGI-Bench CLI

Install the root CLI with:

```bash
uv sync
source .venv/bin/activate
```

Then run commands directly:

```bash
egi-bench --help
```

## `doctor`

Checks local setup and credentials.

```bash
egi-bench doctor
egi-bench doctor --mode deep
egi-bench doctor --mode deep --full-coverage
egi-bench doctor --no-network
egi-bench doctor --check-venvs
```

`doctor --mode deep` checks baseline deep-mode local tools such as Node, npx, and Docker. `--full-coverage` also requires opt-in MCP-Universe credentials.

## `setup`

Installs benchmark virtual environments and then runs data setup.

```bash
egi-bench setup
egi-bench setup --skip-data
```

The command wraps `scripts/install_all.sh`. Each benchmark keeps its own `.venv` to avoid dependency conflicts.

## `data`

Runs data-only setup:

```bash
egi-bench data
```

This wraps `scripts/download_data.sh`.

## `run`

Runs the unified benchmark runner end-to-end (inference, scoring, aggregation).

```bash
egi-bench run --model gpt-4o-mini --mode quick --parallel
egi-bench run --model gpt-4o-mini --mode deep --benchmarks mcpuniverse locobench
```

Common options:

- `--model`: model name to evaluate.
- `--mode`: `quick` or `deep`.
- `--benchmarks`: subset of benchmark names (see table below).
- `--parallel`: run selected benchmarks concurrently.
- `--max-workers`: cap concurrent benchmark workers.
- `--output-dir`: aggregate report and log directory.
- `--base-url`: override the OpenAI-compatible gateway URL.
- `--egi-weights`: per-invocation EGI Score weight overrides, e.g. `M1=0.5,M5=0.2`. Unspecified Ms keep the default from `benchmark_config.yaml::egi_weights`. See [Tuning the EGI Score](scoring.md#tuning-the-egi-score).

Valid `--benchmarks` names:

| CLI name | Benchmark |
|---|---|
| `crmarena` | CRMArena |
| `herb` | HERB |
| `personabench` | PersonaBench |
| `userbench` | UserBench |
| `mcpuniverse` | MCP-Universe |
| `mcpeval` | MCPEval |
| `benchforce` | BenchForce |
| `locobench` | LoCoBench |

To re-aggregate existing per-benchmark outputs without rerunning inference, use `egi-bench report --rescore` (see below).

## `report`

Summarizes aggregate reports. Two modes:

```bash
# Print the latest (or a specific) aggregate report. No scoring, no writes.
egi-bench report
egi-bench report --path results_aggregated/<report>.json
egi-bench report --json

# Re-derive sub-scores from raw per-benchmark outputs (no inference).
# Writes a new aggregate JSON. Optional --benchmarks scopes which to re-score;
# --egi-weights re-aggregates under a different M1-M6 weighting.
egi-bench report --rescore --model gpt-4o-mini --mode quick
egi-bench report --rescore --model gpt-4o-mini --mode quick \
    --benchmarks herb personabench
egi-bench report --rescore --model gpt-4o-mini --mode quick \
    --egi-weights M1=0.20,M5=0.30
```

Common options:

- `--rescore`: re-score from raw per-benchmark outputs. Requires `--model` and `--mode`.
- `--model` / `--mode`: which model+mode raw outputs to score (only with `--rescore`).
- `--benchmarks`: subset of benchmarks to re-score (only with `--rescore`). Uses the same CLI names as `run --benchmarks`.
- `--egi-weights`: re-aggregate under custom M1-M6 weights (only with `--rescore`), e.g. `M1=0.5,M5=0.2`. Unspecified Ms keep their YAML default.
- `--config`: override `benchmark_config.yaml` (only with `--rescore`).
- `--path`: a specific report JSON to read (cannot be combined with `--rescore`).
- `--json`: print the report as raw JSON.
- `--output-dir`: directory to read from and write new aggregates to.

## `clean`

Removes generated aggregate outputs.

```bash
egi-bench clean
egi-bench clean --yes
```

Use `--include-runtime` to also remove `.egi-bench` if future commands create runtime state there.
