---
name: egi-bench-deep-mode
description: Guide users through running EGI-Bench deep mode via the `egi-bench` CLI. Use when the user asks to run `--mode deep`, enable API-keyed domains (MCP-Universe `web_search` / `location_navigation`, MCPEval `national_parks`), provision `SERP_API_KEY` / `GOOGLE_MAPS_API_KEY` / `NPS_API_KEY`, or troubleshoot a deep-mode failure. Does NOT cover quick-mode first-run setup — route that to the `egi-bench-quick-mode` skill.
---

# EGI-Bench Deep Mode

## Goal

Help users run EGI-Bench in **deep mode**. Deep mode runs every benchmark's `deep` profile and, for MCP-Universe specifically, unlocks two API-keyed domains that quick mode deliberately excludes.

**Scope boundary:** this skill assumes quick mode already works for the user. If the user is setting up EGI-Bench for the first time or only needs a smoke test, hand off to `egi-bench-quick-mode`. Come here for deep-mode specifics and credential provisioning.

**Default parallelism:** always use `--parallel --max-workers 2` for deep-mode runs. This is the standard laptop default; higher concurrency hits gateway rate limits.

## What deep mode adds for MCP-Universe

Deep mode's MCP-Universe domain list lives in `benchmark_config.yaml` under `benchmarks.mcpuniverse.modes.deep`. Quick mode (`modes.quick`) only runs the first.

| Domain | MCP servers | Env var | What happens if missing |
|---|---|---|---|
| `financial_analysis` | yfinance + calculator | none | always runs |
| `web_search` | google-search + fetch | `SERP_API_KEY` | skipped with a note |
| `location_navigation` | google-maps | `GOOGLE_MAPS_API_KEY` | skipped with a note |

Env-var gating is declared under `benchmarks.mcpuniverse.optional_domains` in `benchmark_config.yaml`. Missing keys do not fail the deep run — the affected domain is skipped and the surviving domains still produce valid M2 scores.

## What deep mode adds for MCPEval

Deep mode's MCPEval domain list lives under `benchmarks.mcpeval.modes.deep`. Quick runs only `airbnb`.

| Domain | Env var | What happens if missing |
|---|---|---|
| `airbnb` | none | always runs |
| `yfinance` | none | always runs |
| `national_parks` | `NPS_API_KEY` (free, nps.gov developer portal) | skipped with a note |

Env-var gating is declared under `benchmarks.mcpeval.optional_domains` in `benchmark_config.yaml`, mirroring the MCP-Universe pattern. Missing keys do not fail the deep run — `national_parks` is skipped and the surviving domains still produce a valid M2 score.

Scoring uses MCPEval's static tool evaluator (`evaluate_tool_calls_with_both_match_types`): predictions from `eval.py` are diffed against `data/<domain>/evaluation_tasks_verified.jsonl`. Domain score is flexible `average_score` (continuous); strict/flexible success rates and component accuracies live in `raw_metrics`.

## Required environment

Baseline deep mode:

- Provider credentials in `.env` — at minimum `OPENAI_API_KEY` (drives
  the OpenAI routes and the judge / simulator pins, so required for
  apple-to-apple scoring even when the tested model is non-OpenAI).
  Add `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `VERTEX_PROJECT`,
  `SFR_GATEWAY_API_KEY`, `AWS_*`, etc. for whichever routes the user wants active. Per-model
  routing lives in `litellm_proxy/litellm_config.yaml`; before running,
  verify the requested tested model is present as a `model_name` there
  (or is covered by an intentional wildcard route). If it is missing,
  add a `model_list` entry or choose an existing route. See
  `docs/llm-providers.md`.
- The local LiteLLM proxy is auto-spawned by `egi-bench run` on
  demand and torn down on exit; no manual start required. For
  long-running deep-mode runs you may want to start a long-lived
  proxy first with `egi-bench proxy start` so it persists across
  sequential per-benchmark reruns when debugging.
- Installed benchmark venvs and root CLI (`bash scripts/install_all.sh`
  or `egi-bench setup` if CLI is already installed). The script is
  idempotent — it skips existing venvs (checks if `.venv/bin/python` exists).
  If a venv is broken, delete it manually (`rm -rf <BenchmarkName>/.venv`)
  and re-run the script.
- Data setup (included in `scripts/install_all.sh` or run separately
  via `egi-bench data`).

Optional keys, each unlocks one domain:

- `SERP_API_KEY` — MCP-Universe `web_search`. Free tier works for smoke runs.
- `GOOGLE_MAPS_API_KEY` — MCP-Universe `location_navigation`. Billing-enabled Google Cloud API key.
- `NPS_API_KEY` — MCPEval `national_parks`. Free key from nps.gov developer portal.

`run_all.py` loads `.env` at the repo root then `MCP-Universe/.env`; either location works.

Verify with:

```bash
egi-bench doctor --mode deep
egi-bench doctor --mode deep --full-coverage   # requires SERP_API_KEY, GOOGLE_MAPS_API_KEY, NPS_API_KEY
```

## Setup order

1. **Confirm quick mode works** — don't debug deep on top of a broken quick run. Hand off to `egi-bench-quick-mode` if quick fails.
2. **Verify the tested model route** in `litellm_proxy/litellm_config.yaml`. The planned `--model` value must match a configured `model_name`, unless the config intentionally provides a matching wildcard route.
3. **Add optional API keys to `.env`** (root or `MCP-Universe/.env`) before running. Missing keys cause those domains to be silently skipped rather than fail — you won't get coverage for them. Use `egi-bench doctor --mode deep --full-coverage` to see which keys are still missing.
4. **Launch the full suite:**
   ```bash
   egi-bench run --model gpt-4.1-mini --mode deep --parallel --max-workers 2
   ```
5. **Inspect the report's MCP-Universe notes** — any skipped domain prints which env var is missing. Add the key to `.env` and re-run only that benchmark:
   ```bash
   egi-bench run --model gpt-4.1-mini --mode deep --parallel --max-workers 2 --benchmarks mcpuniverse
   ```

Edit `benchmark_config.yaml` directly — `modes.<mode>.domains` takes a list, `max_tasks_per_domain` caps per-domain sampling, `sample_seed` keeps the sample reproducible:

```yaml
benchmarks:
  mcpuniverse:
    modes:
      deep:
        domains:
          - financial_analysis
          - web_search
        max_tasks_per_domain: 30
        sample_seed: 42
```

If you add a new domain that needs an env var, also append it to `optional_domains` so missing keys cause skips, not failures. Then run: `egi-bench run --model <m> --mode deep --benchmarks mcpuniverse`.

## Other MCP-Universe domains (out of scope by default)

Upstream ships several more domains that are not in either profile:

| Domain | What it needs | Why it's out |
|---|---|---|
| `repository_management` | `GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_PERSONAL_ACCOUNT_NAME` | creates real GitHub repos and PRs as side effects |
| `multi_server` | all of the above plus notion | too many moving parts |
| `3d_design` | `BLENDER_APP_PATH`, `MCPUniverse_DIR` + Blender 4.4 install | heavy local install |
| `browser_automation` | `npx playwright install chromium` | non-pip dependency |

Add them via a custom profile only if you understand the prereqs. Never add `repository_management` without a dedicated GitHub test account.

## Runtime expectations

Deep mode is long. Rough pacing at `gpt-4.1`:

- MCP-Universe deep mode (3 domains, full task lists, running parallel across domains): ~2-3 hours.
- Full deep suite (all 8 benchmarks): on the order of 6 hours.
- `--parallel --max-workers 2` is a good laptop default; higher concurrency hits gateway rate limits.

If a benchmark dominates runtime, edit the inline `modes.<mode>` dict in `benchmark_config.yaml` to shrink `num_scenarios`, `max_tasks_per_env`, etc.

## Debugging loop

1. Run `egi-bench report` or read the terminal summary.
2. Check per-benchmark under `domain_scores[<name>]`: `status`, `error_message`, `notes`.
3. For MCP-Universe, per-domain notes tell you which env var is missing.
4. Open the log: `results_aggregated/logs/<benchmark>_deep_<timestamp>.log`.
5. Re-run only the affected benchmark:
   ```bash
   egi-bench run --model gpt-4.1-mini --mode deep --benchmarks mcpuniverse
   ```

## Common fixes (deep mode only)

- **MCP-Universe `web_search` skipped:** `SERP_API_KEY` is not set in either `.env`. Add it and re-run; no re-setup needed.
- **MCP-Universe `location_navigation` skipped:** `GOOGLE_MAPS_API_KEY` not set. Same fix. The key requires billing enabled on Google Cloud.
- **`web_search` runs but returns 0%:** usually the SERP plan is rate-limited or exhausted. Check the log for HTTP 429; upgrade plan or wait.
- **`location_navigation` runs but returns low:** normal — gpt-4.1 passes ~80% of sub-evaluators but only ~15% of whole tasks strictly. The reported score is `sub_eval_pass_rate` (continuous), not `task_pass_rate` (all-or-nothing).
- **Deep run exceeds budget:** reduce the profile's `max_tasks_per_domain` or drop a domain. Keep a `sample_seed` for reproducibility.
- **Stale `*_patched_*.yaml` in `MCP-Universe/mcpuniverse/benchmark/configs/mcpuniverse/`:** the runner sweeps these at startup, but they're gitignored in case. Safe to delete manually too.
- **LiteLLM proxy / upstream API key issues** (e.g.
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SFR_GATEWAY_API_KEY`):
  identical to quick mode. Hand off to the quick-mode skill if the
  root issue is baseline setup.

## When to Hand Off

Redirect to `egi-bench-quick-mode` when:

- the user has not yet run quick mode successfully.
- the failure is a missing provider credential (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `VERTEX_PROJECT`, `SFR_GATEWAY_API_KEY`, …), the local LiteLLM
  proxy not running, root CLI install, or `.env` bootstrap.
- the user only wants a smoke test.

## Response Style

When debugging, quote the specific report field or log error that drives the fix, then provide the shortest rerun command — usually targeted at a single benchmark with `--benchmarks <name>`.
