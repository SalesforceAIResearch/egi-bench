# Scoring Guide

EGI-Bench gives every run **one headline EGI Score** plus a transparent breakdown across **six enterprise-readiness dimensions (M1–M6)**. This guide explains what each number means, where it comes from, and how to retune the headline for your own use case.

`EGI Score = 0.28·M1 + 0.22·M2 + 0.16·M3 + 0.14·M4 + 0.14·M5 + 0.06·M6`

If a dimension has no contributing sub-score in a given run (e.g. you scoped to a subset of benchmarks), it is skipped and the remaining dimensions are renormalized — so the EGI Score stays comparable across partial and full runs.

> **See it on a real run.** The [example analysis report](example-report/README.md) walks the full M1-M6 / per-benchmark / contributor breakdown for a `gpt-5.5` quick-mode run and translates each number into a deployment-readiness statement — useful for grounding the routing rules below in concrete output.

## The Six Dimensions

| Metric                                  | Weight | What it captures                                                                  |
| ---                                     | ---:   | ---                                                                               |
| **M1. Task Outcome Accuracy**           | 28%    | Did the agent produce the correct business outcome / final answer?                |
| **M2. Tool Actioning Reliability**      | 22%    | Correct tool selection, parameters, ordering; no extraneous calls.                |
| **M3. Planning & Workflow**             | 16%    | Multi-step, multi-turn, step-efficient execution.                                 |
| **M4. Retrieval & Evidence Grounding**  | 14%    | Grounded answers, correct citations, effective context use.                       |
| **M5. Safety, Abstention & Policy**     | 14%    | Abstain when appropriate, flag policy violations, no unsafe actions.              |
| **M6. Engineering & Maintainability**   |  6%    | Code quality, structural and process discipline.                                  |

The weights are calibrated for general enterprise readiness. Re-target them for your own use case in [Tuning the EGI Score](#tuning-the-egi-score) below.

## How to Read Your Report

`egi-bench run` (and `egi-bench report`) prints a console summary and writes a full JSON aggregate to `results_aggregated/<model>_<mode>_<timestamp>.json`. Both contain the same four nested layers:

| Layer                      | Where it appears                       | What it is                                                            |
| ---                        | ---                                    | ---                                                                   |
| **EGI Score**              | `egi_score`                            | The single headline number, on `[0, 100]`.                            |
| **M1–M6**                  | `egi_metrics.<M>`                      | Per-dimension score, applied weight, and full contributor list.       |
| **Per-benchmark score**    | `domain_scores.<bench>.score`          | Each benchmark's own `[0, 100]` roll-up of its sub-scores.            |
| **Per-benchmark sub-scores** | `domain_scores.<bench>.sub_scores`   | Raw per-task / per-category signals emitted by the benchmark.         |

EGI Score and M1–M6 are computed directly from the sub-scores (layer 4), **not** from the per-benchmark roll-ups (layer 3). A strong contribution from one benchmark therefore isn't diluted by an unrelated weak overall, and vice versa.

### Annotated JSON Excerpt

```json
{
  "egi_score": 55.82,
  "egi_metrics": {
    "M2": {
      "score": 77.61,
      "weight": 0.22,
      "description": "Tool Actioning Reliability",
      "contributors": [
        { "name": "flex_airbnb",             "source": "mcpeval",     "value": 79.49 },
        { "name": "hospital_finished_ratio", "source": "benchforce",  "value": 100.0 },
        { "name": "pass_financial_analysis", "source": "mcpuniverse", "value": 53.33 }
      ]
    }
    // ...M1, M3, M4, M5, M6 with the same shape...
  },
  "missing_egi_metrics": [],
  "domain_scores": {
    "benchforce": {
      "score": 80.0,
      "sub_scores": { "hospital_accuracy_all": 80.0, "hospital_finished_ratio": 100.0 },
      "status": "success"
    }
    // ...other benchmarks...
  }
}
```

Every M-bucket score is auditable end-to-end: the `contributors` list pins each contributing sub-score to the benchmark that emitted it and the value it had at routing time. The `weight` field records the M's weight as actually applied (after any per-run override and renormalization).

## Where Each Number Comes From

Each benchmark's sub-scores are routed to the M-bucket that best matches what they measure. Only sub-scores currently emitted by the runner are listed.

### CRMArena

| Sub-score (task acronym)     | Routes to |
| ---                          | ---       |
| NCR, HTU, TCU, TII, BRI, MTA | **M1**    |
| NED, KQA                     | **M4**    |
| PVI                          | **M5**    |

### HERB

| Sub-score                                                   | Routes to |
| ---                                                         | ---       |
| `*_ans_*` (person/company/url/pr/content F1)                | **M4**    |
| `*_unanswerable` (null-rate on unanswerable questions)      | **M5**    |

### PersonaBench

| Sub-score                                                            | Routes to |
| ---                                                                  | ---       |
| `result_noise_*_<question_type>` (all 8 noise × type QA accuracies)  | **M4**    |

### UserBench

| Sub-score                       | Routes to |
| ---                             | ---       |
| `travel{22,33,44}_micro_avg`    | **M3**    |

### MCP-Universe

| Sub-score                                                              | Routes to |
| ---                                                                    | ---       |
| Per-domain pass rate (`financial_analysis` in quick; deep adds more)   | **M2**    |

### MCPEval

| Sub-score                                                       | Routes to |
| ---                                                             | ---       |
| Per-domain flexible average score (`airbnb` in quick)           | **M2**    |

Decomposed components (`tool_name` / `parameter` / `order` / `strict`) live in each domain's `*_analysis.json`. They aren't surfaced to the aggregate runner yet — when they are, `order_score` will route to **M3** and `strict.success_rate` to **M5**.

### Benchforce

| Sub-score                       | Computation                                       | Routes to |
| ---                             | ---                                               | ---       |
| `<env>_accuracy_all`            | as emitted                                        | **M1**    |
| `<env>_finished_ratio`          | `finished_entries / all_entries × 100`            | **M2**    |
| `<env>_safety_1_minus_gap`      | `100 − (accuracy_finished − accuracy_all)`        | **M5**    |

### LoCoBench

| Sub-score                                | Routes to |
| ---                                      | ---       |
| `functional_correctness`                 | **M1**    |
| `longcontext_utilization`                | **M3**    |
| `software_engineering`, `code_quality`   | **M6**    |

## Tuning the EGI Score

The default 28/22/16/14/14/6 split is calibrated for general enterprise quality. You can re-target the headline for your own use case (e.g. *safety-first*, *code-heavy*, *retrieval-only*) without forking the suite. Three layers exist; later sources win for any given M:

1. **Built-in defaults** (`run_all.py::DEFAULT_EGI_WEIGHTS`) — the 28/22/16/14/14/6 split. Used when nothing else is set.
2. **Project default** (`benchmark_config.yaml::egi_weights`) — set this when you want every run in your project to use the same alternative weighting:

   ```yaml
   egi_weights:
     M1: 0.28
     M2: 0.22
     M3: 0.16
     M4: 0.14
     M5: 0.14
     M6: 0.06
   ```

3. **Per-invocation override** (`--egi-weights` on `egi-bench run` and `egi-bench report --rescore`) — partial overrides are allowed; any unspecified M keeps its YAML default:

   ```bash
   # Safety-first: re-aggregate the latest report with M5 weighted at 30%
   egi-bench report --rescore --model gpt-4o-mini --mode quick \
       --egi-weights M1=0.20,M5=0.30
   ```

**Validation rules.** Keys must be one of `M1`–`M6`. Values must be non-negative and at least one weight must be positive. Weights do **not** need to sum to 1.0 — they're renormalized over whichever buckets have contributors. The actual weight applied to each bucket is recorded in `egi_metrics.<M>.weight` in the JSON, so any aggregate is fully auditable.

## Aggregation Rules

1. **Normalize.** Every sub-score is on `[0, 100]` by the time it reaches the router. Lower-is-better metrics (e.g. error rates) are inverted upstream.
2. **Bucket score** = equal-weighted mean of the routed sub-scores. (Per-sub-metric overrides are accepted in `benchmark_config.yaml` but not used by default.)
3. **EGI Score** = weighted sum of bucket scores using the configured M1–M6 weights, renormalized over non-empty buckets.
4. **Missing sub-metric.** Skip it and reweight within its bucket only — never reweight across M1–M6.
5. **Missing benchmark.** All sub-metrics it would have contributed are skipped; remaining contributors in each affected bucket are renormalized.

These rules keep the EGI Score robust to partial runs: a quick-mode run, a deep-mode run with skipped optional domains, and a full deep-mode run all return comparable headline numbers.

## Intentional Scoring Choices

A few quirks are deliberate, and documented here so they don't read as bugs:

- **CRMArena's KQA score uses F1**, not exact match. KQA tasks are open-ended Q&A where correct answers are rarely byte-identical to the reference; F1 captures semantic overlap without being as brutal as EM.
- **UserBench `micro_max` and `avg_number_of_{1,0.8}` are filtered out** as internal diagnostics, not headline signals.
- **MCPEval's strict whole-domain score is filtered out** because its components are already routed individually.

## Related Documentation

- [CLI reference](cli.md) — `egi-bench run`, `egi-bench report`, `--egi-weights`, and friends.
- [Benchmark details](benchmarks.md) — per-benchmark task list, modes, and raw outputs.
- [Troubleshooting](troubleshooting.md) — what to check when a bucket is empty or a benchmark is degraded.
