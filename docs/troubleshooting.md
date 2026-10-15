# Troubleshooting

## LiteLLM Proxy Unreachable

`egi-bench run` auto-spawns the proxy, so a "proxy unreachable" error
during a run almost always means the spawn failed (bad config, port
conflict, missing venv). Check status and logs:

```bash
egi-bench proxy status
egi-bench proxy logs -n 50          # last 50 lines of .egi-bench/proxy/proxy.log
```

If the proxy isn't running (e.g. `egi-bench doctor` showed it as down
and you want to verify before a run):

```bash
egi-bench proxy start
curl http://localhost:8008/health/liveliness
```

If the proxy is running but you've just changed `.env` or
`litellm_proxy/litellm_config.yaml`, restart it so the new values are
picked up:

```bash
egi-bench proxy stop && egi-bench proxy start
```

To inspect which models the proxy currently exposes:

```bash
curl http://localhost:8008/v1/models | jq '[.data[].id]'
```

To verify a specific model can actually reach its upstream:

```bash
curl -s -X POST http://localhost:8008/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5-nano","messages":[{"role":"user","content":"ping"}]}' \
  | jq '.choices[0].message.content // .error'
```

A `401` / "AuthenticationError" / "incorrect api key" body means the
provider key for that model's route is missing or invalid; a "model not
found" body means the model is missing from
[`litellm_proxy/litellm_config.yaml`](../litellm_proxy/litellm_config.yaml).

## Missing Root Credentials

Run:

```bash
egi-bench doctor --no-network
```

Set missing values in `.env`. Do not paste secrets into issue reports or chat logs.

## Missing or Incomplete Benchmark Venv

**Symptoms:**
- Benchmarks fail immediately with `ModuleNotFoundError`
- `egi-bench doctor` reports missing venvs
- You see errors like "No module named 'dotenv'" or "No module named 'llama_index'"

**Fix:**

Delete the broken venv and reinstall:

```bash
rm -rf <BenchmarkName>/.venv
bash scripts/install_all.sh
```

Or if you've already installed the CLI:

```bash
rm -rf <BenchmarkName>/.venv
egi-bench setup
```

The install script checks if `.venv/bin/python` exists. If present, it skips installation (assuming the venv was set up correctly). If absent, it runs the full installation commands from requirements.txt.

**Verify all venvs:**

```bash
egi-bench doctor --check-venvs
```

This checks that all 8 benchmark venvs exist with their Python interpreters properly installed.

## MCPEval Fails with "ReferenceError: File is not defined"

**Symptoms:**
- MCPEval fails immediately with Node.js error: `ReferenceError: File is not defined`
- Error occurs in `undici/lib/web/webidl/index.js`
- You're running Node.js v18.x or older

**Root Cause:**
MCPEval's MCP server dependencies require the `File` API, which was added in Node.js v20.

**Fix:**
Upgrade to Node.js 20 or later:

```bash
# Using nvm (recommended)
nvm install 20
nvm use 20

# Or using Homebrew (macOS)
brew install node@20
brew link --overwrite node@20

# Verify version
node --version  # should show v20.x.x or higher
```

After upgrading Node.js, re-run the benchmark:

```bash
egi-bench run --model <model> --mode quick --benchmarks mcpeval
```

## Deep Mode Skips MCP-Universe Domains

Deep mode's MCP-Universe profile lists three domains. `financial_analysis`
always runs. `web_search` needs `SERP_API_KEY` and `location_navigation`
needs `GOOGLE_MAPS_API_KEY` — missing keys appear as skip notes in the
report, not failures. To require both keys be present:

```bash
egi-bench doctor --mode deep --full-coverage
```

## Rerun Only Failed Benchmarks

Use the benchmark names from the report:

```bash
egi-bench run --model gpt-4o-mini --mode quick --benchmarks <name>
```

## Score Existing Outputs

If benchmark commands already ran and you want to re-derive sub-scores:

```bash
egi-bench report --rescore --model gpt-4o-mini --mode quick
```

To re-score only a subset of benchmarks, scope with `--benchmarks`:

```bash
egi-bench report --rescore --model gpt-4o-mini --mode quick \
    --benchmarks crmarena herb userbench mcpuniverse
```
