---
name: egi-bench-analyze-results
description: Translate a finished EGI-Bench aggregate report into a business-facing assessment of what the agent can and cannot be trusted with in real enterprise work, saved as a standalone markdown file with auto-rendered M1-M6 / per-benchmark charts. Use when the user asks to read, analyze, interpret, summarize, diagnose, or compare an EGI-Bench result/report; says things like "what does my report mean", "where is this model production-ready", "where would this model fail in our workflows", "is this model good enough for support / sales / engineering", "write up my benchmark results", "save the analysis", "should we deploy this model". Produces the four-layer table (EGI Score, M1-M6, per-benchmark, sub-scores), a business-anchored capability assessment, and prioritized deployment recommendations (ship-now / defer / do-not-deploy) grounded in `docs/scoring.md` and the enterprise-role mapping in `playbook.md`. Inline-links matplotlib charts under `<report_dir>/analysis/<basename>.md`. Does NOT run benchmarks — for that, hand off to `egi-bench-quick-mode` or `egi-bench-deep-mode`.
---

# EGI-Bench Analyze Results

## Goal

Translate a finished EGI-Bench aggregate JSON report into a business-facing assessment of what the agent can and cannot be trusted with in real enterprise work. Tell the user, in this order:

1. **What the numbers are** — a clean table of EGI Score, M1-M6, and per-benchmark scores. (Evidence layer.)
2. **Where each number comes from** — the strongest and weakest sub-score contributors per M-bucket, *translated into the workflow behaviors they imply* (not just listed). (Evidence layer.)
3. **What this model can and can't be trusted with** — a Capability Assessment anchored to concrete enterprise scenarios (L1 support, internal research, multi-turn intake, junior engineering, …), not score percentages. (Interpretation layer.)
4. **How to deploy it** — Deployment Recommendations split into *ship now with these guardrails* / *defer until X* / *do not deploy*. Score-improvement guidance is appropriate only for users who own the model, and even then is framed as "investing in capability X unlocks use case Y" rather than "lift score Z by N points". (Action layer.)
5. **A standalone markdown report with charts** — the entire analysis written to `<report_dir>/analysis/<basename>.md` via `scripts/build_report.py`, with the M1-M6 radar / per-benchmark bars / contributor strip plot auto-rendered into `<report_dir>/charts/<basename>/` and inline-linked into the markdown. One command produces the full deliverable.

**Framing rule.** Benchmarks are proxies for enterprise roles. Scores are evidence about whether the model can perform those roles. The deliverable is a deployment-readiness verdict. Never describe a finding only as "M3 is at 24%" — always translate to "the agent can't sustain a multi-turn customer interaction past ~3 turns without losing constraints; would need a human takeover for any conversation longer than that". The score is the evidence; the workflow consequence is the finding.

The skill is **read-only on the report** and on the agent under test. It does not rerun benchmarks, edit `.env`, or change `benchmark_config.yaml`. For runs and config changes, hand off (see [When to Hand Off](#when-to-hand-off)).

## First Questions

Before analyzing, confirm:

1. **Which report?** Default to the most recent `*.json` under `results_aggregated/` (and any `results_aggregated_*/` variants the user may have). Accept an explicit path. If multiple candidates exist, list them by mtime and ask.
2. **Comparison run?** If the user wants to compare two reports (e.g. before/after a prompt change, two models), ask for both paths. Treat the second one as the baseline.
3. **Charts?** Offer `scripts/render_charts.py` but never run it without consent — it requires `matplotlib`, which is not in the root venv.

Do not ask the user to paste the JSON into chat — read it from disk.

## Inputs

The aggregate report shape comes from `run_all.py::build_report` and is documented end-to-end in [`docs/scoring.md`](../../../docs/scoring.md). Fields you'll use:

| Field                                | What it is                                                                                |
| ---                                  | ---                                                                                       |
| `model`, `mode`, `timestamp`         | Run identity. Show in the header.                                                         |
| `egi_score`                          | Headline 0-100 score. May be `null` if no bucket had any contributor.                     |
| `egi_metrics.<M>.score`              | Per-bucket score on 0-100. `null` when the bucket is empty.                               |
| `egi_metrics.<M>.weight`             | Weight as actually applied (after override + renormalization).                            |
| `egi_metrics.<M>.contributors[]`     | List of `{name, source, value}` — the auditable inputs to that M-bucket.                  |
| `missing_egi_metrics`                | M-buckets with zero contributors in this run (skipped, not zeroed).                       |
| `domain_scores.<bench>.score`        | Per-benchmark 0-100 roll-up.                                                              |
| `domain_scores.<bench>.sub_scores`   | Raw per-task / per-category signals.                                                      |
| `domain_scores.<bench>.status`       | `success` / `partial` / `error` / `skipped`.                                              |
| `degraded`, `degraded_reasons`       | Run-level health. **Lead with this if `degraded == true`.**                               |
| `total_runtime_seconds`              | Useful when a model "lost" only because the run timed out.                                |

**Backward compat.** Older reports (pre-rename) use `enterprise_readiness_score` / `enterprise_metrics` / `missing_enterprise_metrics`. Read those when present, but always print the new names. `scripts/render_charts.py` already handles both.

## Enterprise Role Mapping

This is the translation layer the entire analysis depends on. Each benchmark and each M-bucket is a proxy for a real enterprise capability. Use these mappings everywhere — Phase 2 patterns, Phase 3 capability bullets, Phase 4 deployment recommendations.

**Each benchmark maps to a real enterprise role:**

| Benchmark      | Real-world role / workflow it proxies                                                |
| ---            | ---                                                                                  |
| CRMArena       | Salesforce admin, sales ops, L1 support agent: case routing, customer-history lookups, policy enforcement, trend reporting |
| HERB           | Internal research analyst / knowledge worker: multi-hop retrieval over wikis, PRs, internal docs; saying "no record found" instead of fabricating |
| PersonaBench   | Executive assistant working with a user's private data (emails, contacts, preferences) under realistic noise |
| UserBench      | Multi-turn customer-facing intake agent (travel, sales, support): gathering requirements over a conversation |
| MCP-Universe   | Production agent calling real third-party APIs (financial, web search, maps) via MCP |
| MCPEval        | Multi-step booking / transaction agent (Airbnb, finance, gov APIs): sequencing tool calls to complete a transaction |
| Benchforce     | Vertical-domain agent (hospital coding, HR ops): operating correctly within domain rules; finishing tasks rather than abandoning |
| LoCoBench      | Junior engineer working in a large unfamiliar codebase: feature implementation, refactoring, code review |

**Each M-bucket maps to a deployment-readiness dimension:**

| M-bucket | Deployment-readiness question it answers |
| --- | --- |
| **M1. Task Outcome Accuracy**         | "Will this agent finish the job correctly when nothing else goes wrong?" — the bar for fully-autonomous deployment. |
| **M2. Tool Actioning Reliability**    | "Can I trust this agent to actually call the API correctly, or will it malform requests?" — the bar for agentic transactions. |
| **M3. Planning & Workflow**           | "Can I hand this agent a multi-step or multi-turn workflow without it losing context?" — the bar for end-to-end automation vs single-turn assist. |
| **M4. Retrieval & Evidence Grounding**| "When this agent cites a source, did it actually read the source?" — the bar for citation-required and audit-traceable use cases. |
| **M5. Safety, Abstention & Policy**   | "Will this agent know when to escalate to a human, or will it confidently fabricate?" — the bar for unsupervised customer-facing use. |
| **M6. Engineering & Maintainability** | "Is the agent's output suitable for production hand-off, or does a human need to clean it up?" — the bar for code/document-generation use cases. |

The full per-M deployment guide and per-benchmark sub-score business interpretations live in [`playbook.md`](playbook.md). Read it on demand when Phase 2 / Phase 3 / Phase 4 needs depth on a specific bucket or benchmark — don't re-derive.

## Workflow

Walk through the five phases below in order. Phases 1-4 produce output the user sees in chat; Phase 5 is the default finishing move (saves a standalone markdown report with auto-rendered charts) and should be skipped only when the user explicitly asks for verbal-only analysis.

```
Analysis Progress:
- [ ] Phase 1: Surface — headline + tables
- [ ] Phase 2: Diagnose — per-bucket and per-benchmark sub-score breakdown
- [ ] Phase 3: Verdict — strengths and weaknesses
- [ ] Phase 4: Recommend — prioritized improvement actions
- [ ] Phase 5: Save report (with auto-rendered charts) — scripts/build_report.py + StrReplace
```

### Phase 1: Surface

Read the report and print **three** tables.

**1a. Run header** (one line):

```
gpt-4o · quick mode · 2026-04-28 20:05 · runtime 1h 41m · status: SUCCESS
```

If `degraded == true`, replace `SUCCESS` with `DEGRADED` and follow the header with the contents of `degraded_reasons[]`. Do not skip this — a degraded run can change every conclusion downstream.

**1b. M1-M6 table** — sorted by `M1..M6` order, not by score:

```
Metric                                Weight   Score   Verdict
------------------------------------- ------ ------- ---------
M1. Task Outcome Accuracy              28%   66.3%   Strong
M2. Tool Actioning Reliability         22%   77.6%   Strong
M3. Planning & Workflow                16%   24.1%   Failing
M4. Retrieval & Evidence Grounding     14%   40.9%   Weak
M5. Safety, Abstention & Policy        14%   53.6%   Mixed
M6. Engineering & Maintainability       6%   51.5%   Mixed
------------------------------------- ------ ------- ---------
EGI Score                                     55.8%   Mixed
```

Use these verdict bands consistently across all output. They're calibrated for current frontier-model performance on enterprise tasks: SOTA models typically land in **Mixed** on the headline EGI Score, so **Strong** and **Production** are reserved for genuinely exceptional dimensions.

| Score   | Verdict        | Meaning                                                          |
| ---     | ---            | ---                                                              |
| 80-100  | Production     | Trustworthy enough to deploy without close human review          |
| 65-79   | Strong         | Above current frontier; clearly best-in-class on this dimension  |
| 50-64   | Mixed          | Frontier territory; current SOTA models live here                |
| 30-49   | Weak           | Clearly behind frontier; recognizable failure mode               |
| 0-29    | Failing        | Fundamental gap on this dimension                                |

For any M with `score == null`, print `--` and add a footnote:
`* M3 had no contributors in this run (UserBench / LoCoBench skipped).`

**1c. Per-benchmark table** — sorted by score descending:

```
Benchmark      Score    Status     Runtime    Sub-scores
-------------- ------- ---------- ---------- ----------
benchforce     80.0%   success    17.5m       4
mcpeval        79.5%   success    11.3m       1
crmarena       57.4%   success    45.7m       9
mcpuniverse    53.3%   success    44.9m       1
locobench      43.5%   success    3.8m        4
personabench   43.9%   success    12.2m       8
herb           25.2%   success    18.8m       6
userbench      19.9%   success    10.4m       3
```

If any benchmark has `status != success`, surface its `error_message` or `partial_reason` directly under the table. Do not hide a partial run inside the score column — it's the most likely cause of a surprising number.

### Phase 2: Diagnose

For each M-bucket and each benchmark, walk the sub-scores. The goal is to make every headline number traceable to one or two concrete observations the user could act on.

**Per M-bucket.** From `egi_metrics.<M>.contributors[]`, sort by `value` descending and surface:

- **Top contributors** (top 1-2): the workflows the model handles well within this dimension.
- **Bottom contributors** (bottom 1-2): the workflows it struggles with.
- **Spread**: if the gap between top and bottom is >40 points, flag it — the bucket score is a misleading average and the contributors paint very different pictures.

For each contributor, do **two things**: state the value, and translate to the workflow behavior. Don't stop at the number.

Example output for one bucket:

```
M3. Planning & Workflow — 24.1% (Failing)
  Top:    longcontext_utilization (locobench)  37.0
            → can stay coherent across a large codebase context, but only on
              short scope; doesn't sustain reasoning to actual completion.
  Bottom: travel{22,33,44}_micro_avg (userbench) all ~20.0
            → cannot run a multi-turn customer intake conversation without
              losing constraints. All three trip-complexity tiers fail
              equally → the collapse happens in the first few turns,
              not at scale.

  Workflow consequence: any enterprise scenario requiring an agent to
  drive a >3-turn conversation, or to compose >5 sequential reasoning
  steps autonomously, will be unreliable without a human in the loop.
```

**Per benchmark.** Open `domain_scores.<bench>.sub_scores` and identify the dominant pattern. Translate each pattern into the workflow behavior it implies — not the score it produces.

- **CRMArena `KQA = 0` while `NCR/HTU/TII` are >60** → the agent handles structured CRM analytics fine but cannot answer open-ended customer-history questions. *Workflow consequence:* OK for routing/triage automation, **not** for a customer-facing FAQ bot drawing on case data.
- **HERB `*_unanswerable` low while `*_ans_*` is mid-range** → the agent will fabricate answers when the corpus has no answer. *Workflow consequence:* deploying as an internal-knowledge bot will produce confident-sounding wrong answers to anything not actually in the docs — a credibility and (for regulated industries) compliance risk.
- **PersonaBench `noise_0.0` >> `noise_0.7`** for the same question type → the model handles clean private data but degrades sharply when records are noisy/duplicated. *Workflow consequence:* fine on a curated CRM, unreliable on raw email/contact stores.
- **Benchforce `accuracy_finished − accuracy_all` is large** → the agent silently gives up on hard items. *Workflow consequence:* throughput numbers will look healthy in dashboards while the *hardest* cases — which are usually the ones a human most needs help with — get quietly dropped.
- **LoCoBench `code_quality` >> `functional_correctness`** → the model writes idiomatic-looking code that doesn't actually work. *Workflow consequence:* dangerous as an autonomous coding agent (PRs look mergeable, fail in prod); fine as a code-review *suggestion* engine where a human still validates.
- **MCPEval `airbnb` mid-range with strict-vs-flexible gap** → the agent picks the right tools but messes up *arguments* or *call order*. *Workflow consequence:* OK for read-only tool flows; risky for transactional flows where a malformed booking actually charges money or creates state.

Reference the [`playbook.md`](playbook.md) cross-cutting patterns when one bucket's anomaly only makes sense in combination with another (e.g. M1 high + M5 low → "writes confident answers, doesn't know when to stop" → over-claiming risk). Don't dump the playbook inline — cite the relevant entry.

### Phase 3: Capability Assessment

Synthesize Phase 2 into a business-facing assessment of **what this model can and cannot be trusted with in real enterprise work**. Two columns, 3-5 bullets each.

**Hard rule.** Each bullet must lead with a concrete enterprise scenario (a real role or workflow), then justify it with sub-score evidence translated into the workflow consequence. Not "Strong on M2 (78%) and Benchforce (80%)" — that's score-talk. Yes "Reliable as an L1 hospital-coding agent on bounded tool surfaces (Benchforce hospital_finished_ratio = 100% means the agent never abandons a task mid-loop; hospital_accuracy_all = 80% means 4 of every 5 cases get coded correctly)." Score is the evidence; the *enterprise scenario* and *what that score implies in production* is the finding.

Use the [Enterprise Role Mapping](#enterprise-role-mapping) at the top of this skill to translate benchmark sub-scores into role-level statements. Use the [`playbook.md`](playbook.md) per-M deployment table for what each score band means as a deployment-readiness statement.

Template:

```
Strengths (what this model can do reliably in enterprise workflows)

- L1 helpdesk-style automations on bounded tool surfaces.
  Benchforce hospital_finished_ratio = 100% (never abandons a workflow
  mid-loop) and MCPEval airbnb flex avg = 79.5% (multi-step booking flows
  succeed) mean this model can drive structured task execution against
  internal APIs. Pair with a fixed tool registry and a retry on schema
  failure and it ships.

- Structured CRM analytics: case routing, top-issue identification,
  transfer counting. CRMArena TII = 83%, TCU = 100% on a sandbox org
  → safe behind a sales-ops dashboard for first-pass categorization.

Weaknesses (workflows this model cannot be trusted with today)

- Multi-turn customer-facing intake conversations.
  UserBench travel{22,33,44} micro-avg all ~20% → the agent collapses
  inside the first 3-4 turns regardless of trip complexity. Deploying
  as a customer-facing booking or support bot will produce abandoned
  conversations and unhappy customers; would need a human takeover
  after every short exchange, defeating the automation case.

- Internal-knowledge / FAQ bot over enterprise docs.
  HERB unanswerable null-rate = 27.5% (the agent fabricates an answer
  72% of the time when the doc set has no answer); HERB ans_person /
  ans_company F1 < 11% (cannot reliably retrieve named entities).
  Risk: a confident-sounding but wrong answer to an internal policy
  question is a credibility hit and, in regulated industries, a
  compliance liability.

- Open-ended customer Q&A from CRM history.
  CRMArena KQA = 0% — when asked an unstructured question that needs
  case data, the agent returns nothing usable. Routing/triage works
  (NCR/HTU/TII >60%); free-form support replies do not.

- Autonomous engineering hand-off on unfamiliar code.
  LoCoBench code_quality = 69 but functional_correctness = 34 →
  generates idiomatic-looking code that doesn't run. Safe as a
  human-reviewed "draft this PR" assistant; not safe as an
  autonomous code-fixing agent.
```

Comparison mode: replace headings with **`Capabilities Gained`** / **`Capabilities Lost`** / **`Capabilities Now Stable`** and frame each as a deployment-readiness change (e.g. "Now safe to deploy as X with these guardrails", "Has lost the ability to be deployed as Y unsupervised", "No longer in scope for Z").

### Phase 4: Deployment Recommendations

Produce **deployment guidance**, not score-tuning advice. The user is asking: *"Given this report, what enterprise work can I trust this model with today, what should I wait on, and what should I rule out?"* — answer that question. Cap at 5 items total across the three categories.

Three categories, ordered top-to-bottom by enterprise impact, not by priority within each:

```
Ship now (with these guardrails)
- [enterprise use case]. Why this is safe today: [evidence].
  Required guardrails: [specific scaffolds — citation-required output
  schema, restricted tool registry, confidence threshold +
  human escalation, etc.].

Defer until [model upgrade / engineering scaffold] is in place
- [enterprise use case]. Blocker: [specific gap from Phase 3].
  Path to ready: [either "wait for a stronger base model" OR
  "build this scaffold around the current model" — be explicit].

Do not deploy
- [enterprise use case]. Why: [evidence translated to deployment
  risk]. Better path: [different approach — different model, human
  workflow, restricted scope, etc.].
```

Each item must:

1. **Lead with a real enterprise use case**, not a metric. "L1 helpdesk triage on a fixed product catalog" — yes. "Lift M3 to 30%" — no.
2. For **Ship now**, name the specific guardrails. Vague advice ("add monitoring") is not actionable; concrete advice ("require the agent to return a `(answer, source_chunk_id)` pair and surface 'No answer found' when the LLM-as-judge confidence is below 0.7") is.
3. For **Defer**, explicitly distinguish *needs-a-stronger-model* from *needs-engineering-around-this-model*. Both are valid; conflating them wastes the reader's time.
4. For **Do not deploy**, give the reader confidence in the negative recommendation by pointing to the specific sub-score patterns that imply unacceptable business risk. Suggest a better path (different model class, human-only workflow, narrowed scope).

**Optional 6th-bullet exception.** If the user explicitly owns the model and asks for capability-improvement guidance ("we trained this, what should we invest in next?"), append one **Model Improvement** bullet. Frame as "investing in capability X would unlock use case Y" — never as "lift score Z by N points". Example: *"Investing in multi-turn state tracking (currently the dominant M3 failure mode per `travel{22,33,44}` collapse) would unlock customer-facing intake and booking automations, which today require human takeover after 3 turns."*

Use [`playbook.md`](playbook.md) for the cross-cutting deployment patterns (e.g. "M1 high + M5 low → over-claiming risk → mandatory citation-required output schema") and the per-M deployment-readiness bands.

In comparison mode, recommendations should focus on *what changed in deployment readiness* — capabilities now safe to deploy that weren't before, capabilities that have regressed and need to be pulled back, etc.

### Phase 5: Save report (with auto-rendered charts)

Default finishing move. Produces a standalone markdown file the user can share, commit, or paste into a doc — with all the deterministic content from Phases 1-2 mechanically rendered, the narrative from Phases 3-4 inserted by you, and three auto-rendered charts inline-linked. One command does everything.

**Step 1 — generate the skeleton + charts.** The `build_report.py` script reads the same JSON the analysis was based on, calls `render_charts.py` as a subprocess to produce the PNGs, and emits a fully-formed markdown with `<!-- AGENT FILL: ... -->` placeholders for the three analytical sections.

```bash
# One-time install (matplotlib is NOT in the root venv):
uv pip install matplotlib

# Default: render charts AND write markdown in one command.
python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \
    --report results_aggregated/<model>_<mode>_<timestamp>.json
# → writes results_aggregated/charts/<basename>/{m1_m6_radar,domain_bars,m_contributors}.png
# → writes results_aggregated/analysis/<basename>.md (with the charts inline-linked)
```

Useful flags:
- `--out path/to/file.md` — write the markdown somewhere other than the default.
- `--compare path/to/baseline.json` — overlay a baseline run on the radar and bar charts (use this in comparison mode).
- `--no-render-charts` — skip the chart subprocess and link only pre-existing PNGs (or a fallback message). Use only if the user explicitly opted out of charts.
- `--force` — overwrite an existing analysis file (otherwise the script refuses).

If `matplotlib` is missing, the chart subprocess fails gracefully: the markdown still gets written, the Charts section carries an install hint, and you should tell the user to run `uv pip install matplotlib` and rerun with `--force`.

The skeleton contains:

| Section                               | Source                                    |
| ---                                   | ---                                       |
| Header (model, mode, EGI Score, runtime, status) | report metadata                |
| Degraded warning block (if `degraded == true`)   | report top-level fields        |
| Executive Summary                     | **AGENT FILL** (2-3 sentences, business-anchored) |
| EGI Score Breakdown table             | mechanical from `egi_metrics`             |
| Per-Benchmark Scores table            | mechanical from `domain_scores`           |
| Per-Bucket Diagnosis (every contributor sorted, with wide-spread flags) | mechanical from `egi_metrics.<M>.contributors` |
| Capability Assessment                 | **AGENT FILL** (Strengths / Weaknesses, each anchored to enterprise scenarios) |
| Deployment Recommendations            | **AGENT FILL** (Ship now / Defer / Do not deploy; ≤5 total) |
| Charts                                | auto-rendered + inline-linked (`![M1-M6 radar](../charts/<basename>/m1_m6_radar.png)`) |
| Appendix: per-benchmark sub-scores    | mechanical                                |
| Appendix: run metadata                | mechanical                                |

The three charts that get auto-rendered:

- `m1_m6_radar.png` — six-spoke radar of M1-M6 vs a 50% reference circle.
- `domain_bars.png` — horizontal bar chart of per-benchmark scores, color-banded by verdict (Failing/Weak/Mixed/Strong/Production).
- `m_contributors.png` — strip plot of every contributor in every M-bucket; useful when one bucket has wide spread.

**Step 2 — fill in the AGENT FILL placeholders.** For each of the three placeholder sections, use `StrReplace` (or the equivalent edit tool) to replace the entire `<!-- AGENT FILL: ... -->` comment block **and** the `_Pending — fill in during analysis._` line beneath it with the narrative from Phases 3 and 4 of your in-chat analysis.

The placeholder comments contain the exact requirements (e.g. *"3-5 bullets each, every claim anchored to a specific sub-score (name, source, value)"*). Honor them — they are the spec for that section.

**(Optional but recommended) Step 3 — annotate the charts.** Each auto-rendered chart has a short caption opportunity below its `![...](...)` link. Use the same `StrReplace` flow to add a one-sentence caption tying the visual to a specific sub-score observation from Phase 2 (e.g. *"M1 and M2 push past the Production ring; M3 collapses inside the 50% reference circle."*). Skip if the chart speaks for itself.

**Comparison mode.** When the user supplied a baseline report, pass `--compare baseline.json` so the charts overlay both runs. In the Strengths/Weaknesses section swap the two headings for `**Improvements**` / `**Regressions**` and write the bullets in delta form (Δ score, Δ contributor). Recommendations should target regressions, not absolute weakest buckets.

**When to skip Phase 5.** Skip only if the user explicitly says "just tell me", "verbal only", "don't save anything", or similar. In every other case, save the report — it is the deliverable.

## Deep-Dive Reference

For the full per-M diagnosis playbook and the cross-cutting interpretation rules (e.g. "M1 high + M5 low = calibration issue"), see [`playbook.md`](playbook.md). Read it on demand when a phase needs more depth, not by default.

For the routing table (which sub-score feeds which M-bucket), see [`docs/scoring.md`](../../../docs/scoring.md) at the repo root. The skill should never re-derive the routing — link to it.

## When to Hand Off

This skill stops at the verdict and recommendations. Hand off when the user wants to act:

- Re-run a single benchmark to validate a fix → `egi-bench-quick-mode` (it owns the `egi-bench run --benchmarks ...` flow).
- Re-run with deep-mode coverage to widen the M-bucket contributor pool → `egi-bench-deep-mode`.
- Audit which env vars / venvs are missing before a re-run → `egi-bench-prereq-check`.
- Re-aggregate the existing per-benchmark outputs under a different M1-M6 weighting (e.g. the user wants the "what would my EGI Score be under a safety-first profile?" answer) → still in scope here, but the actual command lives in CLI:

  ```bash
  egi-bench report --rescore --model <model> --mode <mode> \
      --egi-weights M1=0.20,M5=0.30
  ```

  Then re-analyze the new aggregate file.

## Response Style

- **Lead with a deployment verdict, not a score.** Open with a one-line business statement, then back it with the EGI Score. Example: *"gpt-4o (quick) is ready to ship as an L1 helpdesk-style tool-calling agent on bounded surfaces (Benchforce 80%, MCPEval 79.5%), but cannot be trusted with multi-turn customer interactions (UserBench all benchmarks <22%) or as an internal-knowledge bot without a strong abstention scaffold (HERB unanswerable null-rate 27.5%). EGI Score 55.8% — frontier territory."*
- **Translate every score into a workflow consequence.** No adjective without a number behind it; no number without an enterprise scenario in front of it. *"M3 = 24%"* is half a sentence; *"M3 = 24% means the agent collapses on multi-turn intake conversations within the first 3 turns"* is the finding.
- **Be honest about partial runs.** A degraded report should have its degradation explained before any deployment recommendation is given — incomplete evidence ≠ clean verdict.
- **Cap recommendations at five.** A short list that an exec can act on beats a long list that nobody reads.
- **Avoid score-tuning advice unless the user owns the model.** "Add a per-turn planning step to lift M3 by 8 points" is the wrong level of abstraction for a deployment decision-maker. Save that flavor for the optional 6th-bullet Model Improvement exception in Phase 4, and only when the user has signaled they're the model trainer.
- **Use code references** when you cite the report path, e.g. `results_aggregated/gpt-4o_quick_20260428_200508.json`.
- **Close with the saved file.** After Phase 5, end the response with the path to the generated markdown so the user can open it directly. Example: *"Full deployment write-up (with charts) saved to `results_aggregated/analysis/gpt-4o_quick_20260428_200508.md`."*
- **Never modify the source JSON report or rerun the benchmark suite from this skill.** Edit only the generated markdown analysis file. Suggest re-run commands and let the user run them.
