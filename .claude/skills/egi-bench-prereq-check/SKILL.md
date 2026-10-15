---
name: egi-bench-prereq-check
description: Audit environment-variable prerequisites across all 8 EGI-Bench benchmarks before a run. Use when the user asks to check prereqs, verify credentials, find out why a benchmark is skipping tasks, plan which API keys they need before running `--mode deep`, or says things like "what env vars do I need", "prereq check", "audit setup", "am I missing any keys". This skill does NOT run benchmarks — it only reports what is configured, what is missing, and which benchmarks/domains would be skipped if run now.
---

# EGI-Bench Prereq Check

## Goal

Give the user a per-benchmark, per-domain view of **exactly which environment variables are required, which are missing, which benchmark venvs are installed, and which benchmark coverage would be lost if they run now**. Output is advisory — this skill does not modify `.env` or run the suite.

`egi-bench doctor` does include venv presence checks by default now, but does not walk the per-domain env-var matrix. This skill covers both: env vars + venvs + domain-level gating + the "would-skip" projection.

## Workflow

1. Read `.env` at the repo root. If it does not exist, tell the user to `cp .env.example .env` first and stop.
2. **Check benchmark venv presence.** For each benchmark in `BENCHMARK_NAMES`, look for `<Dir>/.venv/bin/python`. Missing venvs are the most common failure mode for a fresh clone.
3. If the user provides a target tested model, read `litellm_proxy/litellm_config.yaml` and verify that model is present as a `model_name`, unless the config intentionally includes a matching wildcard route. Report a missing tested-model route as a hard pre-run blocker: the LiteLLM proxy will reject the inference check until a `model_list` entry is added or the user chooses an existing route.
4. For each benchmark below, check the env vars listed. Classify each as `set` / `missing` / `placeholder`.
   - `missing` = key absent from `.env` and shell environment.
   - `placeholder` = value looks like `your-...`, `xxxxxxxx`, `<...>`, or an unchanged `.env.example` stub.
   - Treat values with at least one non-placeholder character as `set` without printing the value.
5. Print a report in the format below. Never print secret values — only key names and state.
6. End with a **"would skip / would fail" summary**: missing venvs and missing tested-model routes cause hard failures; missing API keys for optional domains cause skips.

Do not modify `.env`. Do not run benchmarks or install venvs automatically. If the user asks to fix, hand off to `egi-bench-quick-mode` (which owns `egi-bench setup`) or `egi-bench-deep-mode`.

## Output format

```
EGI-Bench prereq audit
======================

[venvs]                                    REQUIRED (hard fail without)
  crmarena              OK       (CRMArena/.venv)
  herb                  OK
  personabench          OK
  userbench             OK
  mcpuniverse           OK
  mcpeval               MISSING  — `cd MCPEval && uv venv && uv pip install -e . && uv pip install -r requirements.txt`
  benchforce            OK
  locobench             OK

[baseline]                                 REQUIRED
  OPENAI_API_KEY        set       (powers OpenAI routes + judge / simulator pins)

[provider keys]                            OPTIONAL (only needed for routes that use them)
  ANTHROPIC_API_KEY     set/missing   — for claude-* model_name routes
  GEMINI_API_KEY        set/missing   — for gemini-* model_name routes
  AWS_ACCESS_KEY_ID     set/missing   — for bedrock/* model_name routes

[tested model route]                       REQUIRED FOR RUN
  gpt-4o-mini           OK/MISSING — must appear as model_name in litellm_proxy/litellm_config.yaml

[crmarena]                                 OPTIONAL (bundled sandbox creds default)
  SALESFORCE_USERNAME   missing   (only needed for custom org / non-'original' org_type)
  ...

[mcpuniverse (native domains)]             PER-DOMAIN
  financial_analysis    yfinance + calculator — (no keys needed)
  web_search            google-search + fetch — SERP_API_KEY [set/missing]
  location_navigation   google-maps — GOOGLE_MAPS_API_KEY [set/missing]

WOULD FAIL on `egi-bench run`:
  - mcpeval: venv not installed
  - tested model route missing: add `model_name: <model>` to litellm_proxy/litellm_config.yaml

WOULD SKIP on `egi-bench run --mode deep`:
  - mcpuniverse/web_search: SERP_API_KEY missing
  - mcpuniverse/location_navigation: GOOGLE_MAPS_API_KEY missing
  ...
```

## Per-benchmark venv install recipes

When a venv is missing or incomplete, recommend:

**Recommended:**
```bash
bash scripts/install_all.sh
```
This is **idempotent**. It checks if `.venv/bin/python` exists for each benchmark. If present, it skips installation. If absent, it runs the full installation. If a venv is broken, delete it manually (`rm -rf <BenchmarkName>/.venv`) and re-run the script.

**Alternative (if root CLI is already installed):**
```bash
egi-bench setup
```

**Single-benchmark manual fix (if needed):**

| Benchmark | Recipe |
|---|---|
| CRMArena | `cd CRMArena && uv venv && uv pip install -r requirements.txt` |
| HERB | `cd HERB && uv venv && uv pip install -r code/requirements.txt` |
| PersonaBench | `cd PersonaBench && uv venv && uv pip install -r requirements.txt` |
| UserBench | `cd UserBench && uv venv && uv pip install -r requirements.txt` |
| MCP-Universe | `cd MCP-Universe && uv venv && uv pip install -e .` |
| MCPEval | `cd MCPEval && uv venv --python 3.12 && uv pip install -e . && uv pip install -r requirements.txt` |
| Benchforce | `cd Benchforce && uv venv && uv pip install -r requirements_text.txt` |
| LoCoBench | `cd LoCoBench && uv venv && uv pip install -r requirements.txt` |

Source of truth is `scripts/install_all.sh`; re-check that file if a recipe here stops working.

## Benchmark Prereq Reference

This table is the authoritative mapping of each benchmark (and each domain it runs) to the env vars it needs. Report against this.

### Baseline — always required

The local LiteLLM proxy needs at least one provider credential. The
shipped `litellm_proxy/litellm_config.yaml` pins the judge / simulator
stack (HERB `gpt4-correctness`, MCP-Universe sub-evaluators, UserBench
TravelGym) to OpenAI, so:

| Var | Notes |
|---|---|
| `OPENAI_API_KEY` | Required. Drives the OpenAI routes *and* the judge / simulator pins. Without it, those benchmarks score 0 even when the tested model is non-OpenAI. |

Provider keys for the optional routes — set whichever the user wants
to evaluate:

| Var | Why |
|---|---|
| `ANTHROPIC_API_KEY` | `claude-*` `model_name` routes (Anthropic direct). |
| `GEMINI_API_KEY` | `gemini-*` `model_name` routes (Google Gemini direct). |
| `VERTEX_PROJECT` / `VERTEX_LOCATION` | `vertex/*` `model_name` routes (Google Vertex AI; uses ADC or `GOOGLE_APPLICATION_CREDENTIALS`). |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | `bedrock/*` `model_name` routes (LiteLLM signs SigV4). |

Per-model routing is declared in `litellm_proxy/litellm_config.yaml`.
For a concrete run target, the requested `--model` must match a
configured `model_name` unless the config intentionally provides a
matching wildcard route. See `docs/llm-providers.md` for the recipes.

### CRMArena — optional, bundled defaults

The `.env.example` at `CRMArena/.env.example` ships working public sandbox credentials; leaving these empty in the repo-root `.env` is fine. Only populate when the public sandbox is rate-limited or the user wants a custom Salesforce org.

| Var | When needed |
|---|---|
| `SALESFORCE_USERNAME` / `SALESFORCE_PASSWORD` / `SALESFORCE_SECURITY_TOKEN` | Custom Salesforce org (non-'original' `org_type` in `benchmark_config.yaml`) |
| `SALESFORCE_B2B_USERNAME` / `..._PASSWORD` / `..._SECURITY_TOKEN` | `org_type: b2b` only |
| `SALESFORCE_B2C_USERNAME` / `..._PASSWORD` / `..._SECURITY_TOKEN` | `org_type: b2c` only |

### HERB — none beyond baseline

Uses the local LiteLLM proxy for LLM calls and ships bundled embedding
settings. The `gpt4-correctness` judge call is pinned to OpenAI in
`litellm_config.yaml`, so `OPENAI_API_KEY` must be set even when the
tested model is non-OpenAI.

### PersonaBench — none beyond baseline

Reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` but the runner injects `dummy` + the LiteLLM proxy URL at subprocess time. Nothing for the user to set.

### UserBench — none beyond baseline

Same as PersonaBench — runner injects the gateway credentials. `TRAVELGYM_DATA_PATH` is optional; defaults to `UserBench/data/`.

### MCP-Universe — native domains

The runner calls MCP-Universe's native `BenchmarkRunner` (via `scripts/run_mcpuniverse.py`) on the domains listed in `benchmark_config.yaml` under `benchmarks.mcpuniverse.modes.{quick,deep}`. Each domain calls specific MCP servers, and server env-var needs come from `MCP-Universe/mcpuniverse/mcp/configs/server_list.json`.

Currently wired in profiles:

| Domain | MCP server(s) | Required env vars | Mode |
|---|---|---|---|
| `financial_analysis` | `yfinance`, `calculator` | none | quick + deep |
| `web_search` | `google-search`, `fetch` | `SERP_API_KEY` | deep (skipped without key) |
| `location_navigation` | `google-maps` | `GOOGLE_MAPS_API_KEY` | deep (skipped without key) |

Out of scope by default (available to add via a custom profile):

| Domain | MCP server(s) | Required env vars / tooling | Why not included |
|---|---|---|---|
| `repository_management` | `github` | `GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_PERSONAL_ACCOUNT_NAME` | real side effects on GitHub |
| `multi_server` | many | all of the above plus `NOTION_API_KEY`, `NOTION_ROOT_PAGE` | heavy setup |
| `3d_design` | `blender` | `BLENDER_APP_PATH`, `MCPUniverse_DIR` + local Blender 4.4.0 | heavy local install |
| `browser_automation` | `playwright`, `date` | none env-wise, but requires `npx playwright install chromium` | non-pip dependency |

**Env chain:** `run_all.py` loads `.env` at the repo root then `MCP-Universe/.env`. Either file can hold these keys. Missing keys are surfaced as "skipped" notes in the report, not failures.

**Config lives in one place:** `benchmark_config.yaml` under `benchmarks.mcpuniverse.modes.{quick,deep}` — a plain dict with `domains`, optional `max_tasks_per_domain`, and `sample_seed`. Edit that file to customize.

### MCPEval — per-domain

Quick mode uses **`airbnb` only** (multi-step tool sequencing, no extra creds). Deep adds `yfinance` and `national_parks`.

| Domain | Mode | Required env vars |
|---|---|---|
| `airbnb` | quick + deep | none |
| `yfinance` | deep | none |
| `national_parks` | deep | `NPS_API_KEY` (free key from nps.gov Developer Portal) |
| Other upstream domains (sqlite, filesystem, special_calculator, travel_assistant, healthcare, sports) | — | none |

**Env chain:** `run_all.py` loads `.env` at the repo root, then the shell. Missing `NPS_API_KEY` is surfaced as a "skipped" note in the report, not a failure — the gating is declared under `benchmarks.mcpeval.optional_domains` in `benchmark_config.yaml`, mirroring the MCP-Universe pattern.

Scoring pipeline: after `eval.py` produces the per-task predictions JSONL, the runner calls MCPEval's static tool evaluator (`evaluate_tool_calls_with_both_match_types`) to diff against the domain's verified ground truth. The reported domain score is **flexible `average_score`** (continuous, 0-100); strict + flexible success rates and per-component accuracies are preserved in `raw_metrics`.

### Benchforce — none beyond baseline

Upstream `.env.example` lists many provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `TOGETHERAI_API_KEY`, `ELEVENLABS_API_KEY`) but in EGI-Bench the runner substitutes the local LiteLLM proxy for all of them. Ignore upstream's list.

### LoCoBench — none beyond baseline

Uses the local LiteLLM proxy via `run_eval_litellm.py`. Data comes from local files (after `scripts/download_data.sh`).

## Placeholder detection rules

Treat a value as `placeholder` (therefore missing for practical purposes) if it matches any of:

- starts with `your-`, `your_`, `YOUR-`
- contains `xxxxxxxx` or `XXXXXX`
- contains `<` and `>` (angle-bracket stubs)
- is literally one of: `placeholder`, `changeme`, `example`, `fill-me-in`

## Optional checks the skill can offer

After the main report, offer (but do not auto-run) these follow-ups:

1. **Shell loading check** — remind the user that the runner loads `.env` via `_load_root_env()` in `run_all.py`, but shell-exported vars take precedence. If a key seems missing, ask whether they have `source .env`-d it manually.
2. **LiteLLM proxy reachability** — offer to run `egi-bench proxy status` (managed/external/stopped + health). The proxy is auto-spawned by `egi-bench run`, so it being "stopped" is normal pre-run; users only need to manage it explicitly when they want a long-lived shared proxy or to inspect logs.
3. **Benchmark venv check** — offer `egi-bench doctor --check-venvs` as a pointer; do not run it automatically.

## When to Hand Off

- User wants to actually run quick mode → `egi-bench-quick-mode`.
- User wants to provision opt-in MCP-Universe credentials or run deep mode → `egi-bench-deep-mode`.
- User wants to rewrite `benchmark_config.yaml` routing → this is a code change; propose an edit but do not hand off to a skill.

## Response Style

- Lead with the one-line verdict: "X missing, Y placeholder, Z set; running now would skip N domains."
- Follow with the per-benchmark table.
- End with the "would skip" summary and the shortest follow-up commands.
- Never print secret values.
- Do not tell the user to paste secrets into chat. When a var is missing, tell them which file to edit (usually `.env`) and cite the external setup link if the reference table above lists one.
