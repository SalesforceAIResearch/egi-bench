# Deep Mode

Deep mode expands coverage beyond the quick smoke path. For MCP-Universe in
particular, quick mode deliberately includes only the `financial_analysis`
domain because it needs no external API keys. Deep mode adds the
API-key-gated domains; missing credentials auto-skip the affected domain with
a note, so deep mode degrades gracefully.

## Baseline deep mode

Requires:

- Provider credentials for whichever upstream serves your `--model`,
  set in `.env`. At minimum `OPENAI_API_KEY` (powers the judge /
  simulator pins; required for apple-to-apple scoring even when the
  tested model is non-OpenAI). Add `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `VERTEX_PROJECT`, `AWS_*` etc. for whichever
  routes you want active — see [`docs/llm-providers.md`](llm-providers.md)
  and [`litellm_proxy/README.md`](../litellm_proxy/README.md).
- The local LiteLLM proxy running (`cd litellm_proxy && bash start_server.sh`).
- Installed benchmark venvs from `egi-bench setup`.
- Data setup from `egi-bench data`.

Check it with:

```bash
egi-bench doctor --mode deep
```

Then run:

```bash
egi-bench run --model gpt-4o-mini --mode deep
```

## MCP-Universe native domains (deep mode)

Deep mode's MCP-Universe domain list lives in `benchmark_config.yaml` under
`benchmarks.mcpuniverse.modes.deep`:

| Domain | MCP server(s) | Env vars | Behavior when missing |
| --- | --- | --- | --- |
| `financial_analysis` | yfinance + calculator | none | always runs |
| `web_search` | google-search + fetch | `SERP_API_KEY` | skipped with note |
| `location_navigation` | google-maps | `GOOGLE_MAPS_API_KEY` | skipped with note |

Env-var gating is declared in the same file under
`benchmarks.mcpuniverse.optional_domains`. The runner reads these variables
from the env chain: root `.env`, then `MCP-Universe/.env`, then shell exports.

## MCPEval domains (deep mode)

Deep mode's MCPEval domain list lives in `benchmark_config.yaml` under `benchmarks.mcpeval.modes.deep`:

| Domain | MCP server | Env vars | Behavior when missing |
| --- | --- | --- | --- |
| `airbnb` | airbnb | none | always runs |
| `yfinance` | yfinance | none | always runs |
| `national_parks` | national_parks | `NPS_API_KEY` | skipped with note |

Env-var gating is declared in the same file under
`benchmarks.mcpeval.optional_domains`, mirroring the MCP-Universe pattern.
The runner reads these variables from the env chain: root `.env`, then the
shell. `NPS_API_KEY` is a free key from nps.gov's developer portal. Quick
mode doesn't include `national_parks`, so this only matters for deep runs.

After each domain's `eval.py` run, the unified runner invokes MCPEval's static tool evaluator (`evaluate_tool_calls_with_both_match_types`) to diff predictions against `data/<domain>/evaluation_tasks_verified.jsonl`. Domain scores report flexible `average_score`; strict and flexible success rates + per-component accuracies live in `raw_metrics`.

## Full-coverage deep mode

Ensure all gated domains can run by setting the relevant keys:

```bash
# Add to .env or MCP-Universe/.env
SERP_API_KEY=...            # unlocks MCP-Universe web_search
GOOGLE_MAPS_API_KEY=...     # unlocks MCP-Universe location_navigation
NPS_API_KEY=...             # unlocks MCPEval national_parks
```

Verify with:

```bash
egi-bench doctor --mode deep --full-coverage
```

## Customizing the MCP-Universe domain list

To swap domains or adjust task counts, edit `benchmark_config.yaml` directly:

```yaml
benchmarks:
  mcpuniverse:
    modes:
      deep:
        domains:
          - financial_analysis
          - web_search
          # comment out or add more domains here
        # max_tasks_per_domain: 30   # cap per domain; omit to run all
        sample_seed: 42
```

Then run: `egi-bench run --model <m> --mode deep --benchmarks mcpuniverse`.

## Other MCP-Universe domains (not included here)

Upstream MCP-Universe ships several more domains that are deliberately out of
both quick and deep mode today:

- `repository_management` — real side effects on GitHub (creates repos, PRs);
  needs `GITHUB_PERSONAL_ACCESS_TOKEN` + `GITHUB_PERSONAL_ACCOUNT_NAME`.
- `multi_server` — combines several external services.
- `3d_design` — needs a local Blender 4.4 install.
- `browser_automation` — no API key but requires
  `npx playwright install chromium`.

To use any of them, add the domain to `modes.<mode>.domains` in
`benchmark_config.yaml` and append its required env vars to
`optional_domains` so missing keys produce skip notes rather than failures.

## Related upstream docs

- `MCP-Universe/README.md` — upstream benchmark and server documentation.
