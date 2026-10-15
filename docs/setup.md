# Setup And Credentials

EGI-Bench keeps shared credentials in one root `.env` file. Commands load this file without overwriting values already exported in the shell.

```bash
cp .env.example .env
```

Required values:

```bash
# Powers the OpenAI routes and the judge / simulator pins (HERB,
# MCP-Universe, UserBench). Required even when --model is non-OpenAI
# to keep scores comparable to main.
OPENAI_API_KEY=your-openai-api-key
```

Optional, set whichever providers you want to route through:

```bash
ANTHROPIC_API_KEY=             # claude-* model_name routes
GEMINI_API_KEY=                # gemini-* model_name routes
VERTEX_PROJECT=                # vertex/* model_name routes
VERTEX_LOCATION=us-central1
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# AWS_ACCESS_KEY_ID=           # bedrock/* routes (LiteLLM signs SigV4)
# AWS_SECRET_ACCESS_KEY=
# AWS_REGION=us-east-1
```

The friendly model name → upstream provider mapping itself lives in
[`litellm_proxy/litellm_config.yaml`](../litellm_proxy/litellm_config.yaml).
To expose a new model under `egi-bench run --model X`, add a
`model_list` entry there. See [`docs/llm-providers.md`](llm-providers.md)
for per-provider recipes (OpenAI, Anthropic, Gemini, Bedrock,
OpenRouter, vLLM/Ollama/TGI) and gotchas (reasoning-model parameter
handling, judge-pin rationale).

## Installation

Install everything (root CLI, benchmark environments, and LiteLLM proxy) with:

```bash
bash scripts/install_all.sh
source .venv/bin/activate
```

This provisions:
- The `egi-bench` CLI command in `.venv/bin/egi-bench`
- Per-benchmark virtual environments (8 separate `.venv` directories)
- The LiteLLM proxy environment (`litellm_proxy/.venv`)
- Required data downloads (LoCoBench scenarios)

After activating the venv, you can use `egi-bench` commands directly. Alternatively, without activation, use `.venv/bin/egi-bench`.

**The script is idempotent:**
- Re-running is safe; existing venvs are skipped (checks if `.venv/bin/python` exists)
- If a venv is incomplete or broken, delete it manually (`rm -rf <BenchmarkName>/.venv`) and re-run the script

**Verify the installation:**

```bash
egi-bench doctor
```

This checks Python version, Node.js version (20+ required for MCPEval), `uv` availability, `.env` presence, provider credentials, and that all 8 benchmark venvs exist.

## LiteLLM Proxy

`egi-bench setup` provisions `litellm_proxy/.venv` for you alongside
the per-benchmark venvs, and `egi-bench run` auto-spawns the proxy
process on demand (waits for `/health/liveliness`, runs the benchmarks,
then tears it down on exit). For most workflows there's nothing to do
manually.

If you want to keep a single long-lived proxy across multiple runs
(saves ~5s startup per run), or to inspect the proxy log while
debugging upstream-provider errors, the `egi-bench proxy` subcommand
is the explicit handle:

```bash
egi-bench proxy start         # spawn detached
egi-bench proxy status        # managed | external | stopped + health
egi-bench proxy logs -f       # tail .egi-bench/proxy/proxy.log
egi-bench proxy stop          # stop a previously-started managed proxy

# Direct sanity checks (work whether proxy was started by egi-bench or by hand):
curl http://localhost:8008/health/liveliness
curl http://localhost:8008/v1/models | jq '[.data[].id]'
```

If you need to start it manually (e.g. on a different port), the
underlying script is still available:

```bash
cd litellm_proxy && bash start_server.sh
```

## Alternative: Using egi-bench setup Command

If you've already installed the root CLI (via `bash scripts/install_all.sh` and activation), you can use the `egi-bench setup` command as a convenience wrapper:

```bash
egi-bench setup
```

This wraps `scripts/install_all.sh` and runs data setup. Like the underlying script, it's safe to re-run and will skip existing venvs.

To install dependencies without data setup:

```bash
egi-bench setup --skip-data
```

To refresh only data:

```bash
egi-bench data
```

**Note:** The first time on a fresh clone, you should use `bash scripts/install_all.sh` directly since the `egi-bench` command won't exist yet. After that, you can use either method.

## Optional Credentials

CRMArena works with bundled public sandbox credentials by default. Set Salesforce variables in `.env` only if you have a custom org:

```bash
SALESFORCE_USERNAME=
SALESFORCE_PASSWORD=
SALESFORCE_SECURITY_TOKEN=
```

MCP-Universe **quick mode** needs no extra keys — it only runs
`financial_analysis` (yfinance + calculator). MCP-Universe **deep mode**
adds two API-keyed domains; provide either or both to unlock them:

```bash
SERP_API_KEY=                # enables web_search domain
GOOGLE_MAPS_API_KEY=         # enables location_navigation domain
```

Either variable may live in `.env` at the repo root or in `MCP-Universe/.env`;
the runner chains both. Missing keys auto-skip the affected domain with a
note in the report, not as a failure. See [Deep mode](deep-mode.md).
