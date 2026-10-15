---
name: egi-bench-quick-mode
description: Guide users through running EGI-Bench quick mode end-to-end via the `egi-bench` CLI. Use when the user asks to run quick mode, smoke-test the suite, set up the quick-mode credential, troubleshoot a quick-mode failure, or inspect a quick-mode report. Does NOT cover deep mode — route deep-mode questions to the `egi-bench-deep-mode` skill.
---

# EGI-Bench Quick Mode

## Goal

Help end users run EGI-Bench in **quick mode** through the root `egi-bench` CLI, using the local LiteLLM proxy for inference, collecting only the credentials quick mode needs, and debugging failures from aggregate reports and per-benchmark logs.

**Scope boundary:** this skill is quick-mode only. Deep mode, API-keyed MCP-Universe domains (`web_search`, `location_navigation`), and any GitHub / Notion / WebArena work belong to the `egi-bench-deep-mode` skill.

## First Questions

Before running commands, confirm:

1. Target model name for `--model` (default `gpt-4.1-mini` if the user has no preference).
2. Whether they want all benchmarks or a subset via `--benchmarks`.
3. Whether to run in parallel. Default to `--parallel --max-workers 2` on laptops.
4. Whether they already have a root `.env` with the quick-mode variable below.

Do not ask users to paste secrets into chat. Ask them to edit `.env`, or give command templates with placeholders.

## Required Credentials (quick mode only)

At minimum at the repo-root `.env`:

- `OPENAI_API_KEY=<your-key>` — required. Drives the OpenAI routes
  *and* the judge / simulator pins (HERB `gpt4-correctness`,
  MCP-Universe sub-evaluators, UserBench TravelGym), so it must be set
  even if the user is testing a non-OpenAI model.

Optional, only set if the user wants to test models from those
providers:

- `ANTHROPIC_API_KEY` — for `claude-*` model_name routes.
- `GEMINI_API_KEY` — for `gemini-*` model_name routes.
- `VERTEX_PROJECT` / `VERTEX_LOCATION` — for `vertex/*` model_name routes
  (uses ADC or `GOOGLE_APPLICATION_CREDENTIALS`).
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` — for
  `bedrock/*` model_name routes.

Per-model routing (which provider serves a given `--model X`) lives in
`litellm_proxy/litellm_config.yaml`. Before running, read that file and
verify the requested tested model is present as a `model_name`. If it is
missing, tell the user to add a `model_list` entry for that model (or pick
an existing route), then restart any already-running proxy. See
`docs/llm-providers.md` for per-provider recipes.

Other quick-mode benchmarks work without additional credentials:

- CRMArena uses bundled public sandbox credentials unless overridden.
- MCP-Universe quick mode runs only the `financial_analysis` domain (yfinance + calculator, no API keys). The other domains (`web_search`, `location_navigation`, etc.) are deep-mode only.
- MCPEval quick mode runs only the `airbnb` domain (no API keys). `yfinance` and `national_parks` (which needs `NPS_API_KEY`) are deep-mode only.
- If the user asks about `SERP_API_KEY`, `GOOGLE_MAPS_API_KEY`, `NPS_API_KEY`, `GITHUB_*`, `NOTION_*`, or any deep-only MCP-Universe / MCPEval domain, redirect to `egi-bench-deep-mode`.

See `.env.example` and `docs/setup.md` for context.

## Standard Workflow

Run commands from the repository root.

1. Set up `.env` if it does not exist:

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` (and any optional provider keys the user wants to use).

2. Install everything (root CLI, benchmark venvs, proxy, data):

```bash
bash scripts/install_all.sh
source .venv/bin/activate
egi-bench --help
```

This is **idempotent**. It checks if `.venv/bin/python` exists for each benchmark. If present, it skips installation. If absent, it runs the full installation. If a venv is broken, delete it manually (`rm -rf <BenchmarkName>/.venv`) and re-run the script.

After activation, use `egi-bench` directly. Without activation, use `.venv/bin/egi-bench`.

**Alternative (if CLI is already installed):**

```bash
egi-bench setup
```

3. The local LiteLLM proxy is auto-spawned by `egi-bench run`, so
   you do not need to start it manually for a normal quick-mode run.
   `scripts/install_all.sh` provisions its venv. To verify state explicitly:

```bash
egi-bench proxy status
```

Before the run, verify the tested model route exists in
`litellm_proxy/litellm_config.yaml`. The requested `--model` must match a
configured `model_name`, unless the config intentionally provides a
matching wildcard route.

If you want to keep a long-lived proxy across multiple runs (saves
~5s of startup per run) or need to tail upstream errors while
debugging:

```bash
egi-bench proxy start          # idempotent if already up
egi-bench proxy logs -f        # tail .egi-bench/proxy/proxy.log
```

If a provider key was missing or stale when the proxy started,
restart it after updating `.env`:

```bash
egi-bench proxy stop && egi-bench proxy start
```

4. Verify the installation:

```bash
egi-bench doctor
```

This checks Python version, Node.js version (20+ required for MCPEval), `uv` availability, `.env` presence, provider credentials, and that all 8 benchmark venvs exist.

If only data needs refreshing:

```bash
egi-bench data
```

5. Run all benchmarks in quick mode:

```bash
egi-bench run --model gpt-4.1-mini --mode quick --parallel --max-workers 2
```

Subset:

```bash
egi-bench run --model gpt-4.1-mini --mode quick --parallel --max-workers 2 \
    --benchmarks herb personabench userbench
```

6. Inspect the latest aggregate report:

```bash
egi-bench report
```

JSON reports and logs live under `results_aggregated/`.

## Debugging Loop

When a quick-mode run fails or is degraded:

1. Run `egi-bench report` or read the terminal summary.
2. Check report fields:
   - Top-level: `missing_metrics`, `missing_contributors`, `degraded_reasons`.
   - Per-benchmark under `domain_scores[<name>]`: `status`, `error_message`, `notes`.
3. Open the matching log under `results_aggregated/logs/<benchmark>_quick_<timestamp>.log`.
4. Fix the smallest clear cause.
5. Re-run only the failed benchmark first:

```bash
egi-bench run --model gpt-4.1-mini --mode quick --benchmarks <benchmark-name>
```

6. Re-run the full quick suite after targeted fixes pass.

## Common Fixes (quick mode)

- **LiteLLM proxy unreachable mid-run:** the auto-spawn failed. Run
  `egi-bench proxy logs -n 50` to see the actual startup error
  (commonly: missing provider key, port conflict, malformed config).
  Fix and re-run; the next `egi-bench run` will respawn it.
- **Upstream API key missing:** set the relevant provider key
  (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  `VERTEX_PROJECT`, `AWS_*`, …) in `.env`. If a long-lived proxy
  was started via `egi-bench proxy start`, restart it
  (`egi-bench proxy stop && egi-bench proxy start`) so it picks up
  the new env. The auto-spawned per-run proxy already reads the
  current env at every spawn.
- **Proxy inference check fails:** verify the requested `--model` is
  declared in `litellm_proxy/litellm_config.yaml`
  (`curl http://localhost:8008/v1/models` lists everything currently
  exposed); add a `model_list` entry for it or pick one that's already
  there. Default fallback: `--model gpt-4.1-mini`.
- **Missing root CLI or incomplete installation:** `bash scripts/install_all.sh`.
- **Missing or broken benchmark venv:** Delete the broken venv (`rm -rf <BenchmarkName>/.venv`) and run `bash scripts/install_all.sh` or `egi-bench setup`.
- **CRMArena auth failure with bundled creds:** the public sandbox in `connect_sandbox.py` may be down or rate-limited. Either wait, or set `SALESFORCE_USERNAME` / `SALESFORCE_PASSWORD` / `SALESFORCE_SECURITY_TOKEN` in `.env` for a custom org.
- **MCP-Universe quick mode asks for external credentials:** verify `benchmark_config.yaml` quick mode lists only `filesystem`, and run with `--mode quick`.
- **Parallel run is noisy or resource constrained:** retry with `--max-workers 1` or drop `--parallel`.
- **Existing results need rescoring only:** `egi-bench report --rescore --model <model> --mode quick`.

## When to Hand Off

Redirect to `egi-bench-deep-mode` when the user asks:

- to run `--mode deep`
- about `doctor --mode deep` or `--full-coverage`
- about MCP-Universe `github` / `notion` / `playwright_webarena` categories
- about WebArena Docker images, Notion integrations, GitHub eval orgs
- why a deep-mode run is slow or times out

## Response Style

Give concrete next commands and explain what each step verifies. When debugging, quote the specific report field or log error that drives the fix, then provide the shortest rerun command that validates it.
