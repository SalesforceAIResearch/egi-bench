# EGI-Bench Analysis Playbook

Business-facing interpretation of EGI-Bench reports. Used by `SKILL.md` Phases 2-4 to translate scores into deployment-readiness statements — *not* to recommend score-tuning fixes. Read on demand when a phase needs depth on a specific role, M-bucket, or cross-cutting pattern.

The playbook is organized in five layers:

1. **Enterprise role mapping** — every benchmark is a proxy for a real enterprise role. This is the translation layer the rest of the analysis depends on.
2. **Per-M deployment readiness** — what each M score band means for deployment, and which use cases each band unlocks / blocks.
3. **Per-benchmark sub-score patterns** — what each pattern says about the model's fit for the role that benchmark proxies.
4. **Cross-cutting deployment patterns** — combinations across M-buckets and their deployment implications.
5. **Reading comparison reports** — capability deltas across runs.

A short **Model Improvement Appendix** at the end keeps the score-tuning recipes for users who own the model and ask explicitly. Do not lead with it; the deliverable is a deployment verdict.

Score routing (which sub-score feeds which M) is the source of truth in [`docs/scoring.md`](../../../docs/scoring.md). Do not re-derive it here.

---

## 1. Enterprise Role Mapping

For each benchmark, this section names the real-world role it proxies, what "production-ready" looks like for that role, and what the most common deployment failure mode is when the model isn't ready.

### CRMArena → Salesforce admin / sales-ops / L1 support agent

- **Workflows it covers:** case routing, customer-history lookups, transfer-count and handle-time analytics, monthly trend reporting, named-entity disambiguation, policy-violation flagging, knowledge-base Q&A.
- **Production-ready looks like:** structured analytics (NCR, HTU, TII, TCU, BRI, MTA) all >70 *and* policy/grounding tasks (PVI, KQA, NED) >60. The agent can run a sales-ops dashboard's first pass without supervision.
- **Most common failure mode:** strong on structured analytics, fails on free-form Q&A — model handles "what's the average handle time for region 3?" but returns garbage for "what was the customer's last issue?". Deployment implication: behind a structured-query UI, not a chat surface.

### HERB → Internal research analyst / knowledge worker

- **Workflows it covers:** multi-hop retrieval over enterprise docs (wikis, PRs, tickets, content); knowing when *no answer exists* in the corpus.
- **Production-ready looks like:** `*_ans_*` F1 scores >50 across entity types *and* `*_unanswerable` null-rate >60. The agent can be an "ask the company" bot.
- **Most common failure mode:** answers everything, including questions with no answer in the corpus → confident-sounding fabrications. In regulated industries this is a compliance event, not a UX problem.

### PersonaBench → Executive assistant with private-data access

- **Workflows it covers:** answering questions over a user's emails, contacts, preferences, social context — under realistic noise (duplicates, partial records, ambiguity).
- **Production-ready looks like:** `result_noise_0.7_*` >50 across all four question types. The agent can answer about real (noisy) personal data, not just curated data.
- **Most common failure mode:** strong on `noise_0.0` but collapses on `noise_0.7` → fine on a manually-curated CRM, useless on raw email/contact stores. Deployment implication: requires an upstream data-cleaning pipeline before the agent sees the data.

### UserBench → Multi-turn customer-facing intake agent

- **Workflows it covers:** travel booking, sales discovery, support intake — anywhere the agent has to gather requirements over a conversation.
- **Production-ready looks like:** `travel{22,33,44}_micro_avg` >50, with smooth degradation from 22 → 44 (handles complex requests less well than simple, but not catastrophically).
- **Most common failure mode:** flat collapse — `travel22 ≈ travel33 ≈ travel44 ≈ 20%` — meaning the agent fails inside the first 3-4 turns regardless of complexity. Deployment implication: cannot run customer-facing chat unsupervised; would need a human-takeover-after-N-turns scaffold.

### MCP-Universe → Production agent calling real third-party APIs

- **Workflows it covers:** financial analysis (yfinance + calculator), web search (SERP), location/maps (Google Maps).
- **Production-ready looks like:** per-domain pass rate >70. The agent can drive real API integrations.
- **Most common failure mode:** sub-50% pass on `financial_analysis` (the no-credentials baseline) means the model can't reliably use *any* tool — a tool-calling problem, not a credentials problem. Deployment implication: do not ship as an agentic tool-caller until this is addressed.

### MCPEval → Multi-step booking / transaction agent

- **Workflows it covers:** sequencing tool calls to complete a transaction (Airbnb, finance, gov APIs).
- **Production-ready looks like:** `flex_<domain>` >70 *and* the strict success rate within 15-20 points of flex (low strict-flex gap means arguments and call order are right, not just tool selection).
- **Most common failure mode:** flex high (~80) but strict low (~40) → model picks the right tools but malforms arguments or sequences calls wrong. Risky for transactional flows where a malformed booking *actually charges money*.

### Benchforce → Vertical-domain agent (hospital coding / HR ops)

- **Workflows it covers:** specialized agents that have to (a) operate within domain rules, (b) finish what they start, (c) abstain when they shouldn't act.
- **Production-ready looks like:** `<env>_accuracy_all` >70, `<env>_finished_ratio` >90, `<env>_safety_1_minus_gap` >85.
- **Most common failure mode:** `accuracy_finished` >> `accuracy_all` → the agent silently abandons hard cases. Throughput dashboards look healthy while the cases that most need help get dropped. Deployment implication: any deployment must measure abandonment, not just finished-case accuracy.

### LoCoBench → Junior engineer in a large unfamiliar codebase

- **Workflows it covers:** feature implementation, refactoring, code review across multi-file repositories.
- **Production-ready looks like:** `functional_correctness` >65, `code_quality` and `software_engineering` both >65, `longcontext_utilization` >55. The agent can land a small PR.
- **Most common failure mode:** `code_quality` >> `functional_correctness` → idiomatic-looking code that doesn't run. Dangerous as an autonomous coder (PRs look mergeable, fail in prod); fine as a "draft this for me" suggestion engine where a human reviews.

---

## 2. Per-M Deployment Readiness

For each M-bucket: the deployment question it answers, what each score band means in deployment terms, and the deployment patterns / scaffolds that mitigate weakness at lower bands.

### M1. Task Outcome Accuracy (28% weight)

**Deployment question:** Will this agent finish the job correctly when nothing else goes wrong? — the bar for fully-autonomous task completion.

| M1 score | Deployment-readiness statement                                                                 |
| ---      | ---                                                                                            |
| 80+      | Ready for autonomous task completion on the workflow types covered by contributing benchmarks. |
| 65-79    | Ship as autonomous on bounded scope; gate on task complexity / risk for harder cases.          |
| 50-64    | Frontier territory. Use as a *first-draft* generator with mandatory human approval.            |
| 30-49    | Research-assistant tier. Don't deploy as a transactional agent.                                |
| <30      | Do not deploy autonomously on this task type.                                                  |

**Deployment patterns that mitigate low M1:**

- **Draft + approve.** Agent produces a candidate, a human approves. Lifts effective accuracy without lifting the model's accuracy.
- **Output schema validation.** Reject any answer that doesn't conform to the expected structure — catches format-collapse failures (the canonical CRMArena KQA = 0 case).
- **Scope routing.** If M1 is high on simple sub-scores and tanks on hard ones (large within-bucket spread), route only the simple tasks to the agent and the rest to a human.

### M2. Tool Actioning Reliability (22% weight)

**Deployment question:** Can I trust this agent to actually call the API correctly, or will it malform requests? — the bar for agentic transactions.

| M2 score | Deployment-readiness statement                                                                              |
| ---      | ---                                                                                                         |
| 80+      | Production-ready as a tool-calling agent on real APIs.                                                      |
| 65-79    | Ship for read-only tool flows; gate write-side flows on a schema-validation layer.                          |
| 50-64    | OK for read-only; **risky for transactional** flows where malformed calls have real-world cost.             |
| 30-49    | Do not ship as an agent. Use the model only for tool-call *suggestions*, then have a human or rule execute. |
| <30      | The model isn't a viable tool caller for this surface.                                                      |

**Deployment patterns that mitigate low M2:**

- **Restricted tool registry.** Present the agent only the 2-3 tools needed for the current step. Drops the malformation rate sharply.
- **Schema-validate-then-retry.** Reject malformed calls before they hit the API; retry with the validation error in the prompt.
- **Dry-run mode for transactions.** For write-side flows (booking, charging, modifying state), insert a confirmation step that previews the call before execution.

### M3. Planning & Workflow (16% weight)

**Deployment question:** Can I hand this agent a multi-step or multi-turn workflow without it losing context? — the bar for end-to-end automation vs single-turn assist.

| M3 score | Deployment-readiness statement                                                                                |
| ---      | ---                                                                                                           |
| 80+      | Ready for end-to-end multi-step / multi-turn automation.                                                      |
| 65-79    | Ship for medium-length flows (5-10 turns / steps); gate longer flows on summary-and-handoff scaffolds.        |
| 50-64    | Single-turn or short-sequence assist only; expect failures past ~5 turns.                                     |
| 30-49    | Restrict to single-turn use. Multi-turn intake or multi-step planning will collapse early.                    |
| <30      | Cannot sustain a workflow. Treat purely as a request-response component, not an agent.                        |

**Deployment patterns that mitigate low M3:**

- **Human-takeover-after-N.** Set a hard turn limit; escalate to a human past that. Cheap to implement, recovers customer-facing intake use cases.
- **Per-turn state summary.** Inject a structured running-state object every K turns ("constraints satisfied so far / next constraint to ask about") so the agent doesn't have to reconstruct it from scratch.
- **Workflow decomposition.** Break long workflows into staged services that pass typed state between steps, instead of relying on one long agent loop.

### M4. Retrieval & Evidence Grounding (14% weight)

**Deployment question:** When this agent cites a source, did it actually read the source? — the bar for citation-required and audit-traceable use cases.

| M4 score | Deployment-readiness statement                                                                                            |
| ---      | ---                                                                                                                       |
| 80+      | Ready for grounded Q&A and citation-required surfaces.                                                                    |
| 65-79    | Ship for grounded Q&A on a curated corpus; gate broader corpora on a re-ranker scaffold.                                  |
| 50-64    | Ship as a "linked search" experience (results + agent summary), not as a closed-Q&A bot.                                  |
| 30-49    | Do not ship as a knowledge bot. Citations will be unreliable; ground-truth verification effort exceeds the agent's value. |
| <30      | Knowledge use cases are out of scope. The model cannot reliably use evidence even when given it.                          |

**Deployment patterns that mitigate low M4:**

- **Citation-required output schema.** Refuse any answer not paired with a chunk ID; surface the chunk to the user. Turns a hallucination risk into a transparency feature.
- **Re-ranker between retrieval and generation.** Cross-encoder over top-k chunks before they reach the LLM. Big wins on entity-level retrieval (HERB person/company F1).
- **Linked-search UX.** Don't promise a closed answer. Show the retrieved chunks with the agent's summary as scaffolding — failures are recoverable by the user reading the source.

### M5. Safety, Abstention & Policy (14% weight)

**Deployment question:** Will this agent know when to escalate to a human, or will it confidently fabricate? — the bar for unsupervised customer-facing use.

| M5 score | Deployment-readiness statement                                                                                                |
| ---      | ---                                                                                                                           |
| 80+      | Ready for unsupervised customer-facing surfaces. The agent will abstain or escalate on its own when appropriate.              |
| 65-79    | Ship customer-facing with a confidence-threshold escalation rule; spot-check abstention behavior on edge cases.               |
| 50-64    | Internal-facing only, or customer-facing with a mandatory human-in-the-loop on uncertain answers.                             |
| 30-49    | The agent will over-claim regularly. Do not put it on a brand-facing surface unsupervised; risk of authoritative wrong answers. |
| <30      | The agent has no functional abstention behavior. Treat every answer as suspect; require external verification.                 |

**Deployment patterns that mitigate low M5:**

- **Answerability gate.** Pre-generation check: "Is the answer derivable from context? If no, return `'I can't answer this from what's available.'`" Single highest-leverage M5 fix.
- **Confidence + escalation.** Force `(answer, confidence)` schema; route below-threshold to human.
- **Citation-required (overlap with M4).** Forces grounding which incidentally surfaces uncertainty — if the agent can't find a chunk to cite, it can't fabricate one.
- **Policy preamble.** For policy-flagging use cases (CRMArena PVI), prepend the relevant policy excerpt and require an explicit yes/no judgment — turns abstention into a structured decision.

### M6. Engineering & Maintainability (6% weight)

**Deployment question:** Is the agent's output suitable for production hand-off, or does a human need to clean it up? — the bar for code/document-generation use cases.

| M6 score | Deployment-readiness statement                                                                                  |
| ---      | ---                                                                                                             |
| 80+      | Output ships as-is to production code review.                                                                   |
| 65-79    | Output is a usable starting point; light editing needed.                                                        |
| 50-64    | Output requires meaningful clean-up before merging. OK for "draft the boilerplate" use cases.                   |
| 30-49    | Output is reference material, not a deliverable. Use the agent for ideas, not for code that ships.              |
| <30      | Code-generation use cases are out of scope.                                                                     |

**Deployment patterns that mitigate low M6:**

- **Style preamble + linter loop.** Cheap; works on purely cosmetic gaps.
- **Test-first prompting.** Forces the agent to think about correctness before structure — addresses the common `code_quality >> functional_correctness` pattern that's actually an M1 problem dressed as an M6 one.
- **PR review tier, not PR author tier.** Restrict deployment to "review this PR and suggest changes" rather than "author this PR".

---

## 3. Per-Benchmark Sub-Score Patterns

For each benchmark: the patterns to look for in `domain_scores.<bench>.sub_scores` and their workflow consequences.

### CRMArena

| Pattern                                                               | What it means for deployment                                                                                                          |
| ---                                                                   | ---                                                                                                                                   |
| `KQA = 0` while `NCR/HTU/TII` >60                                     | Agent handles structured analytics fine but cannot do free-form CRM Q&A. **OK for triage, not for chat.**                              |
| All structured-analytics scores >70 *but* `PVI` <50                   | Strong dashboard agent, weak compliance agent. Don't put it in front of policy-sensitive workflows.                                    |
| `NED` low *and* `KQA` low                                             | Entity disambiguation is broken — the agent can't tell "John Smith" the customer from "John Smith" the agent. Risky for outbound use. |
| Wide spread within structured analytics (e.g. TCU=100, MTA=50)         | Agent does atomic queries fine but breaks on multi-step aggregation. Restrict to single-query workflows.                               |

### HERB

| Pattern                                                                       | What it means for deployment                                                                                                |
| ---                                                                           | ---                                                                                                                          |
| `*_unanswerable` null-rate <40 with mid-range `*_ans_*`                       | **Critical:** the agent will fabricate when no answer exists. Do not deploy as a knowledge bot without an abstention gate.   |
| `*_ans_url`, `*_ans_pr` >>` *_ans_person`, `*_ans_company`                    | Retrieves *structural* evidence well, fails on *named entities*. Likely a chunking issue around proper nouns.                |
| All `*_ans_*` clustered in 30-50 range                                        | Generic mid-range retriever quality. A re-ranker scaffold can lift this materially before considering a model swap.          |
| `*_ans_content` low while entity scores OK                                    | Free-text grounding is the weak link — the agent retrieves correctly but misuses what it retrieved.                          |

### PersonaBench

| Pattern                                                              | What it means for deployment                                                                                       |
| ---                                                                  | ---                                                                                                                 |
| `noise_0.0_*` strong, `noise_0.7_*` collapses                        | Brittle to noise. Fine on curated data, useless on raw user data. **Pre-clean the corpus or don't deploy.**         |
| `Basic_information` weak across noise levels                         | Factual recall is the bottleneck. RAG/retrieval improvements will do more than model swaps.                          |
| `Subjective` and `Preference` strong, `Social` weak                  | Agent is good with explicit signals (likes/dislikes) but poor with relational context. Limit scope to single-user. |
| All four types weak even at `noise_0.0`                              | The LLM itself is the bottleneck — retrieval improvements won't help.                                                |

### UserBench

| Pattern                                            | What it means for deployment                                                                                                                          |
| ---                                                | ---                                                                                                                                                    |
| Flat collapse (`travel{22,33,44}` all ~20)         | Multi-turn intake is broken from turn 1. **Cannot run a customer conversation unsupervised — full stop.**                                              |
| Smooth degradation (`travel22 > travel33 > travel44`) | Constraint-handling capacity issue — agent runs out of state. OK for short conversations; cap turn limit at where degradation starts.                |
| `travel22` strong, `travel33/44` collapse          | Multi-constraint reasoning is the cliff. Fine for single-need intakes; not for needs that compose.                                                     |

### MCP-Universe

| Pattern                                                  | What it means for deployment                                                                                                                                  |
| ---                                                      | ---                                                                                                                                                            |
| `financial_analysis` <50                                 | Cannot reliably use tools that don't even need credentials. **The tool-calling stack is the bottleneck**, not the API integrations.                            |
| `financial_analysis` >70 but `web_search` low (deep)     | API-credential tools degrade — likely model is overwhelmed by tool descriptions. Trim the tool registry per request.                                            |
| All deep domains >65                                     | Strong general-purpose tool-caller. Ship as an MCP-driven agent on real APIs.                                                                                  |

### MCPEval

| Pattern                                              | What it means for deployment                                                                                                                                              |
| ---                                                  | ---                                                                                                                                                                        |
| `flex_<domain>` mid (~70) + strict <40 (gap >30)     | Agent picks tools right but misorders or malforms arguments. **Risky for transactional flows** where the cost of a wrong call is real (charging money, modifying records). |
| `flex_<domain>` and strict both close + low          | Tool selection itself is wrong. Deeper problem; restrict deployment to read-only.                                                                                          |
| `flex_<domain>` and strict both close + high (>75)   | Production-ready transactional agent for this domain.                                                                                                                       |

### Benchforce

| Pattern                                                          | What it means for deployment                                                                                                          |
| ---                                                              | ---                                                                                                                                    |
| `accuracy_finished` >> `accuracy_all` (large safety_gap)         | Agent silently abandons hard cases. Dashboards will look healthy; the hardest cases get dropped. **Measure abandonment, not throughput.** |
| `finished_ratio` <80                                             | Agent doesn't complete the loop on a meaningful share of cases. Likely a tool-call or planning issue, not a domain knowledge issue.    |
| `accuracy_all` strong, `accuracy_finished` strong, `safety_gap` ~100 | Solid vertical-domain agent — accuracy is real (not gamed by abandonment), agent is reliable end-to-end.                                |

### LoCoBench

| Pattern                                                                  | What it means for deployment                                                                                                                              |
| ---                                                                      | ---                                                                                                                                                       |
| `code_quality` >> `functional_correctness`                               | **Idiomatic code that doesn't work.** Dangerous as an autonomous coder; fine as a draft-and-review assistant.                                              |
| `software_engineering` >> `code_quality`                                 | Mechanical adherence to rubric, ugly code. Engineers will accept the structure but rewrite the implementation.                                             |
| `longcontext_utilization` low while `functional_correctness` OK         | Agent solved an easier sub-problem and ignored the long context. Restrict to small-scope tasks; don't hand it whole repos.                                  |
| All four scores cluster in 60-70 range                                   | Solid junior-engineer-tier output. OK for first-draft PRs in low-criticality areas; pair with a senior reviewer.                                            |

---

## 4. Cross-Cutting Deployment Patterns

Combinations of M-bucket scores have specific deployment implications that are stronger than reading any single bucket alone.

| Pattern (across M-buckets)                                            | What it means for deployment                                                                                                                                               |
| ---                                                                   | ---                                                                                                                                                                         |
| **M1 high, M5 low**                                                   | Agent answers confidently when uncertain. Deploy with a mandatory citation-required output schema or a confidence-threshold + human-escalation rule. Without these, expect authoritative wrong answers in production. |
| **M2 high, M3 low**                                                   | Tools work in isolation; plans don't compose. Ship as a single-turn tool-execution component, *not* an autonomous agent. If you need agency, build the planning layer outside the LLM.                                  |
| **M4 high, M1 low**                                                   | Retrieves correctly but reasons wrong on what it retrieved. Ship as a "linked search" experience (results + summary), not a closed-Q&A bot — the user can recover from a bad summary if they can see the source.        |
| **M2 low, M1 OK on Benchforce only**                                  | Tool-surface mismatch on the more open MCP benchmarks. Tool descriptions need work; do not blame the model. Bounded internal-tool deployments still work.                                                               |
| **LoCoBench `code_quality` >> `functional_correctness`**              | Restrict coding deployments to PR-review tier (suggest changes) rather than PR-author tier (write code that ships).                                                                                                     |
| **CRMArena `KQA = 0` while `NCR/HTU > 60`**                           | Output-format mismatch, not knowledge gap. Deploy behind a structured-query UI; don't promise free-form chat.                                                                                                          |
| **HERB `*_unanswerable` <30 while `*_ans_*` >50**                     | Critical hallucination risk on internal-knowledge surfaces. Mandatory abstention gate before deployment; without it, this is a compliance event waiting to happen.                                                      |
| **PersonaBench `noise_0.0` strong, `noise_0.7` collapses**            | Bottleneck is data quality, not the LLM. Invest in upstream data cleaning before swapping models.                                                                                                                       |
| **All M1-M6 clustered within 10 points**                              | Either an exceptionally well-rounded agent (if cluster >65) or a base-model-ceiling problem (if cluster <50). Well-rounded → ship broadly with light guardrails. Ceiling → swap the base model before further tuning.  |
| **`degraded == true` with one M-bucket empty**                        | Don't draw deployment conclusions about the empty bucket. Re-run the failed benchmark first; the bucket may turn out fine.                                                                                              |

---

## 5. Reading Comparison Reports

When the user supplied two reports (before/after a prompt change, model A vs model B):

1. **Compute deltas at every layer**, then frame them as **capability changes**, not score changes. *"M3 +10 → safe to deploy as a 5-turn intake agent (was 3-turn cap)"* — yes. *"M3 increased 10 points"* — no.
2. **Lead with the capability change that matters most for deployment.** Largest change in `weight × headroom-toward-deployment-threshold` is usually the right measure.
3. **Flag regressions specifically.** A change that gains M3 but loses M5 is net-positive on EGI but the M5 regression is a *production risk* worth surfacing on its own — *"this version is now safe for longer conversations but no longer safe for unsupervised customer-facing use"*.
4. **Use comparison-mode headings:** Capabilities Gained / Capabilities Lost / Capabilities Now Stable. Recommendations should target *what to redeploy* and *what to roll back*, not *what scores to lift*.
5. **When deltas are small** (|Δ EGI| < 1.0), say so explicitly — *"within run-to-run noise; treat as no capability change"*.

---

## Appendix: Model Improvement Recipes (use only when the user owns the model)

The skill's primary deliverable is a deployment-readiness verdict for users who *consume* a model. When the user is the model trainer and has explicitly asked for capability-improvement guidance, this appendix preserves the highest-leverage interventions per M-bucket — framed as "investing in capability X unlocks use case Y", not as score lifts.

| If you want to unlock...                                                              | Invest in...                                                                                                  |
| ---                                                                                   | ---                                                                                                            |
| Customer-facing intake / multi-turn booking automations (currently blocked by M3)     | Multi-turn state tracking (the dominant `travel{22,33,44}` failure mode is per-turn state loss).               |
| Internal-knowledge / FAQ bots (currently blocked by M5)                               | Calibrated abstention training. Single largest lift on HERB unanswerable.                                      |
| Closed-Q&A from enterprise corpora (currently blocked by M4)                          | Entity-aware retrieval (re-ranker + smaller chunks for proper-noun-heavy corpora).                             |
| Autonomous PR-author tier deployments (currently blocked by M1 + M6 in LoCoBench)     | Test-first reasoning for code generation. Moves both `functional_correctness` and `software_engineering`.      |
| Production transactional MCP agents (currently blocked by M2 + MCPEval strict)        | Schema-grounded tool calling (the `flex` vs `strict` gap is largely an arguments/order issue, not selection).  |
| Vertical-domain agents that can't gracefully abstain (Benchforce safety gap)          | Calibrated confidence + abandonment training. Closes the `accuracy_finished − accuracy_all` gap.               |

These are the same interventions a score-tuning playbook would recommend, but framed in terms of which enterprise use cases each unlocks. Use them as the optional 6th-bullet "Model Improvement" item in Phase 4 when (and only when) the user has signaled they're the model trainer.
