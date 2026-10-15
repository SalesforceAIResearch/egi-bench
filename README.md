# EGI-Bench

**EGI-Bench** (Enterprise General Intelligence Benchmark) measures how ready an LLM is to power real enterprise agent workflows end-to-end. It consolidates eight production-grade benchmarks spanning CRM operations, enterprise search, personal-data QA, travel planning, MCP tool use, healthcare and HR agent workflows, and long-context software engineering, behind a single runner that emits one headline **EGI Score** and a transparent breakdown across six dimensions of enterprise readiness.

The point isn't just a headline number. The point is a credible, multi-axis view of *how far a model is from being trusted as the engine of an enterprise agent* — and *which axis* still needs work.

---

## Table of Contents

- [What EGI-Bench Measures](#what-egi-bench-measures)
- [Benchmarks](#benchmarks)
- [Architecture Overview](#architecture-overview)
- [Getting Started](#getting-started)
- [Model Support](#model-support)
- [Agent Skills (Cursor / Claude Code)](#agent-skills-cursor--claude-code)
- [Common Commands](#common-commands)
- [Credentials and Deep Mode](#credentials-and-deep-mode)
- [Outputs](#outputs)
- [Documentation](#documentation)
- [References](#references)

---

## 📊 What EGI-Bench Measures

Real enterprise tasks fail along many axes: wrong final answer, wrong tool call, hallucinated citation, unsafe action, brittle code, runaway plans. A single accuracy number hides which axis is broken. EGI-Bench scores every run across **six sub-metrics (M1–M6)**, each calibrated to a distinct dimension of enterprise readiness, that combine into the **EGI Score**:


| Metric                                    | Weight | What it measures                                                     |
| ----------------------------------------- | ------ | -------------------------------------------------------------------- |
| **M1. 🎯 Task Outcome Accuracy**          | 28%    | Did the agent produce the correct business outcome or final answer?  |
| **M2. 🔧 Tool Actioning Reliability**     | 22%    | Correct tool selection, parameters, ordering; no extraneous calls.   |
| **M3. 🗺️ Planning & Workflow**           | 16%    | Multi-step and multi-turn execution that is step-efficient.          |
| **M4. 🔍 Retrieval & Evidence Grounding** | 14%    | Grounded answers, correct citations, effective context use.          |
| **M5. 🛡️ Safety, Abstention & Policy**   | 14%    | Abstain when appropriate, flag policy violations, no unsafe actions. |
| **M6. ⚙️ Engineering & Maintainability**  | 6%     | Code quality and structural/process discipline.                      |


`EGI Score = 0.28·M1 + 0.22·M2 + 0.16·M3 + 0.14·M4 + 0.14·M5 + 0.06·M6`

Sub-scores from each benchmark are routed to the M-bucket that best matches what they measure — so a model that wins on raw QA accuracy but skips abstention questions sees the cost in **M5**, not buried inside the headline. Weights are configurable per use case (safety-first, code-heavy, …) via `--egi-weights` without forking the suite, and every contributor to every M is preserved in the JSON report so the score is auditable end-to-end. See the [Scoring Guide](docs/scoring.md) for the full routing table, an annotated report walkthrough, and the tuning recipes.

## 🏆 Benchmarks

Eight benchmarks contribute sub-scores to the EGI Score. Each row shows the realistic enterprise scenario it covers and which EGI sub-metrics it feeds.


| Domain               | Benchmark    | What the agent has to do                                                                           | Feeds      |
| -------------------- | ------------ | -------------------------------------------------------------------------------------------------- | ---------- |
| CRM                  | CRMArena     | Resolve Salesforce-style CRM cases over a sandbox org                                              | M1, M4, M5 |
| Enterprise search    | HERB         | Multi-hop retrieval over enterprise documents, including unanswerables                             | M4, M5     |
| Personal data        | PersonaBench | Answer QA over noisy synthetic private user data                                                   | M4         |
| Travel agents        | UserBench    | Multi-turn travel planning against a simulated user                                                | M3         |
| MCP tools            | MCP-Universe | Native MCP-Universe domains (quick: financial_analysis; deep adds web_search, location_navigation) | M2         |
| MCP tools            | MCPEval      | Auto-synthesized MCP tasks (quick: airbnb; deep adds yfinance, national_parks)                     | M2         |
| Healthcare & HR      | Benchforce   | Domain-grounded hospital and HR agent tasks                                                        | M1, M2, M5 |
| Software engineering | LoCoBench    | End-to-end software-engineering scenarios over large repositories                                  | M1, M3, M6 |


Per-benchmark raw signals (F1, exact match, sub-evaluator pass rate, `average_score`, 0–5 rubric scores, …) are preserved end-to-end in the report, so any value in M1–M6 traces back to its source sub-score and originating benchmark.

## 🏗️ Architecture Overview

EGI-Bench is a thin orchestration layer around eight self-contained benchmark repositories. The diagram below shows how a single `egi-bench run` command flows through the system:

```
egi-bench run --model <name> --mode quick|deep
        │
        ├─► LiteLLM Proxy (localhost:8008)
        │       routes to OpenAI / Anthropic / Gemini / Bedrock / Vertex / Azure / vLLM / Ollama
        │       judge & simulator calls are pinned to fixed model names for apple-to-apple scoring
        │
        ├─► 8 Benchmark Runners (each isolated in its own .venv)
        │       CRMArena  ──► M1, M4, M5
        │       HERB      ──► M4, M5
        │       PersonaBench ► M4
        │       UserBench ──► M3
        │       MCP-Universe ► M2
        │       MCPEval   ──► M2
        │       Benchforce ──► M1, M2, M5
        │       LoCoBench ──► M1, M3, M6
        │
        └─► Aggregator
                Sub-scores ──► M1–M6 weighted sum ──► EGI Score
                results_aggregated/<model>_<mode>_<timestamp>.json
```

## 🚀 Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- `[uv](https://github.com/astral-sh/uv)`
- API keys for the providers you plan to evaluate — typically at
least `OPENAI_API_KEY` (used by the judge / simulator pins, so
required for apple-to-apple scoring even if the tested model is
non-OpenAI). Add `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`VERTEX_PROJECT`, `AWS_*` etc. for whichever upstreams you want to
route through. The
local LiteLLM proxy that fans these out to the right backend lives in
`[litellm_proxy/](litellm_proxy/README.md)`.

### 1. Clone this repository

```bash
git clone <repo-url> egi-bench
cd egi-bench
```

### 2. Configure credentials

All shared credentials live in `.env` at the repository root:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```bash
# Powers the OpenAI routes and the judge / simulator pins.
# Required even when --model is non-OpenAI to keep scores comparable.
OPENAI_API_KEY=your-openai-api-key

# Optional — set whichever providers you want to route through:
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
```

The model-to-provider mapping itself is declared in
`[litellm_proxy/litellm_config.yaml](litellm_proxy/litellm_config.yaml)`.
Before running, confirm the tested model you plan to pass to
`egi-bench run --model <name>` appears as a `model_name` in that file.
If it is not present, add a `model_list` entry for the route and
restart any already-running proxy so the new config is loaded.

### 3. Install benchmark environments and CLI

```bash
bash scripts/install_all.sh
source .venv/bin/activate
```

This provisions the root `egi-bench` CLI, per-benchmark virtual environments, the `[litellm_proxy/](litellm_proxy/README.md)` venv, and downloads required data. After activating the venv, you can use `egi-bench` commands directly. Alternatively, without activation, use `.venv/bin/egi-bench`.

The script is **idempotent** and safe to re-run. It auto-detects incomplete installations (e.g., venv directories that exist but are missing packages) and repairs them automatically.

**Verify the installation:**

```bash
egi-bench doctor
```

`egi-bench doctor` verifies the install — by default it checks every per-benchmark venv exists and that dependencies are properly installed. To sanity-check prerequisites *before* installing, use `egi-bench doctor --no-check-venvs --no-network`.

### 4. Run an evaluation

**Prefer Cursor or Claude Code?** See [Agent Skills](#agent-skills-cursor--claude-code) for `/egi-bench-quick-mode` and `/egi-bench-deep-mode` slash commands that walk the same flow end-to-end — no CLI flags to memorize. The rest of this section covers the manual CLI path.

Run the full quick-mode suite sequentially:

```bash
egi-bench run --model gpt-4o-mini --mode quick
```

To shorten wall-clock time, opt into parallel execution. Tune `--max-workers` to match your upstream rate limits:

```bash
egi-bench run --model gpt-4o-mini --mode quick --parallel --max-workers 2
```

Print the latest saved report without rerunning:

```bash
egi-bench report
```

## 🔌 Model Support

EGI-Bench routes every benchmark's LLM call through a local
**[LiteLLM Proxy](litellm_proxy/README.md)** on `http://localhost:8008/v1`.
The proxy maps each `--model` to a provider via `[litellm_proxy/litellm_config.yaml](litellm_proxy/litellm_config.yaml)`,
so the same `egi-bench run --model X` command works for any model
LiteLLM understands — **OpenAI**, **Anthropic** (Claude),
**Google Gemini**, **AWS Bedrock**, **Vertex AI**, **OpenRouter**,
**Azure OpenAI**, and self-hosted servers (vLLM, Ollama, TGI). No
benchmark adapter code knows or cares which upstream is serving the
request — they all speak the standard OpenAI wire protocol against
`localhost:8008/v1`.

**Apple-to-apple scoring is preserved.** Several benchmarks
(HERB `gpt4-correctness` judge, MCP-Universe sub-evaluators,
UserBench TravelGym simulator) request fixed model names like
`gpt-4` / `gpt-4.1` directly. The shipped `litellm_config.yaml`
**pins** these names to OpenAI regardless of which model is under
test, so scores stay comparable across runs even when you're
benchmarking Claude or Gemini. To use that pin, keep `OPENAI_API_KEY`
set even when the tested model lives elsewhere.

See `[docs/llm-providers.md](docs/llm-providers.md)` for the recipe
to add a provider, per-provider gotchas (Anthropic system-prompt
translation, Bedrock SigV4, reasoning-model parameter handling), and
the judge-pinning rationale.

## ✨ Agent Skills (Cursor / Claude Code)

If you're using Cursor or Claude Code, four agent skills under `[.claude/skills/](.claude/skills/)` automate the most common EGI-Bench workflows. They guide you through the same steps documented in [Getting Started](#getting-started), pick the right `egi-bench` flags, and read your reports for you. No need to memorize CLI options or the M1-M6 routing.

Each skill can be invoked two ways:

- **Slash command — recommended.** Type the skill's name as a slash command — e.g. `/egi-bench-quick-mode` — and it activates deterministically, every time.
- **Natural-language trigger.** Describe what you want in plain English and the agent auto-selects the matching skill from its description. Convenient, but activation depends on phrasing — prefer the slash form when reliability matters.


| Skill                                                                             | What it does                                                                                                                                                                                             |
| --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[/egi-bench-quick-mode](.claude/skills/egi-bench-quick-mode/SKILL.md)`           | Walks a full quick-mode run end-to-end (setup → credentials → run → first report)                                                                                                                        |
| `[/egi-bench-deep-mode](.claude/skills/egi-bench-deep-mode/SKILL.md)`             | Walks a deep-mode run including API-keyed MCP-Universe / MCPEval domains                                                                                                                                 |
| `[/egi-bench-prereq-check](.claude/skills/egi-bench-prereq-check/SKILL.md)`       | Audits env vars and per-benchmark venvs across all 8 benchmarks before a run, without running anything                                                                                                   |
| `[/egi-bench-analyze-results](.claude/skills/egi-bench-analyze-results/SKILL.md)` | Translates a finished aggregate report into a deployment-readiness write-up with auto-rendered M1-M6 / per-benchmark / contributor charts — produced the [example report](docs/example-report/README.md) |


Skills are an optional convenience layer; everything they do can also be run directly via the `egi-bench` CLI documented below and in `[docs/cli.md](docs/cli.md)`.

## 🛠️ Common Commands

Beyond the [Getting Started](#getting-started) flow, these are the commands you'll reach for most often. See `[docs/cli.md](docs/cli.md)` for the full reference.

```bash
# Check deep-mode local prerequisites (Node, Docker, etc.)
egi-bench doctor --mode deep

# Require full deep-mode opt-in credentials (GitHub, Notion, WebArena)
egi-bench doctor --mode deep --full-coverage

# Install benchmark venvs without re-downloading data
egi-bench setup --skip-data

# Refresh benchmark data only
egi-bench data

# LiteLLM proxy management (only needed for power users; `egi-bench run`
# auto-spawns the proxy on demand)
egi-bench proxy start    # spin up a long-lived proxy across multiple runs
egi-bench proxy status
egi-bench proxy logs -f  # tail upstream provider errors
egi-bench proxy stop

# Run a subset of benchmarks
egi-bench run --model gpt-4o-mini --mode quick --benchmarks herb personabench

# Re-aggregate existing per-benchmark outputs without rerunning the benchmarks
egi-bench report --rescore --model gpt-4o-mini --mode quick

# Re-score only a subset of benchmarks from existing raw outputs
egi-bench report --rescore --model gpt-4o-mini --mode quick \
    --benchmarks crmarena herb userbench mcpuniverse

# Re-aggregate under a custom M1-M6 weighting (e.g. safety-first profile);
# unspecified Ms keep their default from benchmark_config.yaml::egi_weights
egi-bench report --rescore --model gpt-4o-mini --mode quick \
    --egi-weights M1=0.20,M5=0.30

# Run the deep-mode suite
egi-bench run --model gpt-4o-mini --mode deep --parallel --max-workers 2

# Remove generated aggregate outputs
egi-bench clean
```

## 🔑 Credentials and Deep Mode

**Quick vs deep at a glance.** Both modes produce a real, scored EGI aggregate — they differ in coverage breadth, not in evaluation fidelity. *Quick mode* runs a capped subset of tasks per benchmark and skips the three optional API-keyed domains, finishing in a few hours with just the baseline provider credentials; it's the default for most evaluation runs. *Deep mode* uncaps most task budgets and adds the API-keyed domains documented below (`web_search`, `location_navigation`, `national_parks`); end-to-end runtime can reach ~8 hours depending on the upstream model's latency. The per-benchmark coverage matrix lives in `[benchmark_config.yaml](benchmark_config.yaml)` and the full runbook in `[docs/deep-mode.md](docs/deep-mode.md)`.

All shared credentials live in the root `.env`; shell variables take precedence. The baseline provider-key setup is covered in [Configure credentials](#2-configure-credentials) above (with model-routing details in [Model Support](#model-support) and `[docs/llm-providers.md](docs/llm-providers.md)`). Deep mode additionally expects benchmark venvs and downloaded data from `egi-bench setup`.

Deep mode's MCP-Universe profile adds two API-keyed domains:

- `SERP_API_KEY` unlocks the `web_search` domain.
- `GOOGLE_MAPS_API_KEY` unlocks the `location_navigation` domain.

Either key may live in `.env` at the repo root or in `MCP-Universe/.env`; the runner loads both. Missing keys are reported as skipped notes, not failures, so a partial deep run still produces a valid aggregate.

Deep mode's MCPEval profile adds one API-keyed domain:

- `NPS_API_KEY` unlocks the `national_parks` domain (free key from the [NPS developer portal](https://www.nps.gov/subjects/developer/get-started.htm)).

Same gating semantics as MCP-Universe: a missing `NPS_API_KEY` auto-skips `national_parks` with a note, not a failure, so a partial deep run still produces a valid aggregate. See `[docs/deep-mode.md](docs/deep-mode.md)` for the full per-domain credential matrix.

## 📄 Outputs

Aggregate reports and logs are written under `results_aggregated/`:

```text
results_aggregated/
├── <model>_<mode>_<timestamp>.json
└── logs/
    ├── crmarena_<mode>_<timestamp>.log
    └── ...
```

Use `egi-bench report` to reprint the latest aggregate summary and `egi-bench clean` to remove generated aggregate outputs.

## 📚 Documentation

- [CLI reference](docs/cli.md)
- [Setup and credentials](docs/setup.md)
- [LLM providers and routing](docs/llm-providers.md)
- [Reasoning-model registry runbook](docs/reasoning-models.md) — when and how to register a new reasoning / thinking model so its `max_tokens` budget gets bumped automatically across every benchmark
- [Deep mode](docs/deep-mode.md)
- [Benchmark details](docs/benchmarks.md)
- [Scoring guide (EGI Score and M1–M6)](docs/scoring.md)
- [Example analysis report — gpt-5.5 quick](docs/example-report/README.md) — a worked end-to-end report (tables, charts, deployment recommendations) produced by the `[egi-bench-analyze-results](.claude/skills/egi-bench-analyze-results/SKILL.md)` skill
- [Troubleshooting](docs/troubleshooting.md)

## License

This project is released for research purposes only under the [Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC 4.0)](LICENSE.txt) license. Commercial use is not permitted.

## 🔗 References

- CRMArena: [SalesforceAIResearch/CRMArena](https://github.com/SalesforceAIResearch/CRMArena)
- HERB: [SalesforceAIResearch/HERB](https://github.com/SalesforceAIResearch/HERB), [arXiv](https://arxiv.org/abs/2506.23139)
- PersonaBench: [SalesforceAIResearch/PersonaBench](https://github.com/SalesforceAIResearch/personabench), [arXiv](https://arxiv.org/abs/2502.20616)
- UserBench: [SalesforceAIResearch/UserBench](https://github.com/SalesforceAIResearch/UserBench)
- MCP-Universe: [SalesforceAIResearch/MCP-Universe](https://github.com/SalesforceAIResearch/MCP-Universe)
- MCPEval: [SalesforceAIResearch/MCPEval](https://github.com/SalesforceAIResearch/MCPEval), [arXiv](https://arxiv.org/abs/2507.12806)
- Benchforce: [SalesforceAIResearch/benchforce](https://github.com/SalesforceAIResearch/benchforce)
- LoCoBench: [SalesforceAIResearch/LoCoBench](https://github.com/SalesforceAIResearch/LoCoBench), [arXiv](https://arxiv.org/abs/2509.09614)

