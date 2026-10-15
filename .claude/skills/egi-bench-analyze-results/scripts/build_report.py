#!/usr/bin/env python3
"""Build a markdown analysis report from an EGI-Bench aggregate JSON.

Reads an aggregate JSON report produced by ``egi-bench run`` (or
``egi-bench report --rescore``) and emits a markdown file with all
deterministic content pre-filled:

  - run header (model, mode, timestamp, runtime, status)
  - degraded-run warning block (when applicable)
  - M1-M6 score breakdown table (with verdict bands)
  - per-benchmark score table
  - per-bucket diagnosis with all contributors sorted descending,
    plus a "wide spread" flag when max-min > 40
  - per-benchmark sub-score listing (every raw signal, in source order)
  - charts section — by default the script first invokes ``render_charts.py``
    to write the radar / bars / contributors PNGs into
    ``<report_dir>/charts/<basename>/``, then inline-links them in the
    markdown. Pass ``--no-render-charts`` to skip rendering.
  - run metadata appendix

Sections that require analytical reasoning are emitted with explicit
``<!-- AGENT FILL: ... -->`` placeholders for the agent (or a human
reviewer) to replace afterward:

  - Executive Summary
  - Strengths and Weaknesses
  - Priority Recommendations

The script handles both the current ``egi_score`` / ``egi_metrics``
schema and the legacy ``enterprise_readiness_score`` /
``enterprise_metrics`` schema produced by older runs.

Stdlib-only on its own, but auto-rendering charts requires ``matplotlib``
in the active environment (one-time ``uv pip install matplotlib``). If
matplotlib is missing the chart subprocess fails gracefully and the
markdown still gets written, with an install hint in the Charts section.

Usage:
    python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \\
        --report results_aggregated/<model>_<mode>_<timestamp>.json

    # Custom output location:
    python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \\
        --report path/to/report.json \\
        --out   path/to/analysis.md

    # Skip chart rendering:
    python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \\
        --report path/to/report.json --no-render-charts

    # Overlay a baseline run on the rendered charts:
    python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \\
        --report path/to/run.json --compare path/to/baseline.json

    # Overwrite an existing analysis file:
    python .claude/skills/egi-bench-analyze-results/scripts/build_report.py \\
        --report path/to/report.json --force
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

M_ORDER = ("M1", "M2", "M3", "M4", "M5", "M6")
M_FULL_NAMES = {
    "M1": "Task Outcome Accuracy",
    "M2": "Tool Actioning Reliability",
    "M3": "Planning & Workflow",
    "M4": "Retrieval & Evidence Grounding",
    "M5": "Safety, Abstention & Policy",
    "M6": "Engineering & Maintainability",
}

# Verdict bands. Half-open intervals [lo, hi) so 50.0 lands in Mixed, not Weak,
# matching the SKILL.md table and the chart script. Calibrated for current
# frontier-model performance on enterprise tasks: SOTA typically lands in
# Mixed, so Strong / Production are reserved for genuinely exceptional scores.
VERDICT_BANDS: List[Tuple[float, float, str]] = [
    (0, 30, "Failing"),
    (30, 50, "Weak"),
    (50, 65, "Mixed"),
    (65, 80, "Strong"),
    (80, 100.001, "Production"),
]

CHART_FILES = (
    ("m1_m6_radar.png", "M1-M6 radar"),
    ("domain_bars.png", "Per-benchmark scores"),
    ("m_contributors.png", "M-bucket contributor distribution"),
)

WIDE_SPREAD_THRESHOLD = 40.0


# ---------------------------------------------------------------------------
# Schema helpers (forward + legacy)
# ---------------------------------------------------------------------------


def _egi_score(report: dict) -> Optional[float]:
    return (
        report.get("egi_score")
        or report.get("enterprise_readiness_score")
        or report.get("overall_score")
    )


def _egi_metrics(report: dict) -> Dict[str, dict]:
    return report.get("egi_metrics") or report.get("enterprise_metrics") or {}


def _missing_egi_metrics(report: dict) -> List[str]:
    return list(
        report.get("missing_egi_metrics")
        or report.get("missing_enterprise_metrics")
        or []
    )


def _verdict(score: Optional[float]) -> str:
    if score is None:
        return "n/a"
    for lo, hi, name in VERDICT_BANDS:
        if lo <= score < hi:
            return name
    return "Unknown"


def _fmt_runtime(seconds: Optional[float], *, compact: bool = False) -> str:
    """Human runtime. ``compact=True`` drops the parenthetical seconds for tables."""
    if seconds is None:
        return "n/a"
    if seconds >= 3600:
        primary = f"{seconds / 3600:.2f}h"
    elif seconds >= 60:
        primary = f"{seconds / 60:.1f}m"
    else:
        primary = f"{seconds:.1f}s"
    if compact:
        return primary
    return f"{primary} ({seconds:.0f}s)"


def _fmt_score(score: Optional[float]) -> str:
    return f"{score:.1f}%" if score is not None else "—"


def _fmt_iso_to_human(iso: Optional[str]) -> str:
    if not iso:
        return "n/a"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_header(report: dict, source: Path) -> List[str]:
    model = report.get("model", "unknown-model")
    mode = report.get("mode", "unknown-mode")
    egi = _egi_score(report)
    verdict = _verdict(egi)
    timestamp = _fmt_iso_to_human(report.get("timestamp"))
    runtime = _fmt_runtime(report.get("total_runtime_seconds"))
    status = "DEGRADED" if report.get("degraded") else "SUCCESS"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# EGI-Bench Analysis Report — {model} ({mode})",
        "",
        f"- **Model:** `{model}`",
        f"- **Mode:** `{mode}`",
        f"- **EGI Score:** **{_fmt_score(egi)}** ({verdict})",
        f"- **Run timestamp:** {timestamp}",
        f"- **Total runtime:** {runtime}",
        f"- **Status:** {status}",
        "",
        f"> Generated from `{source.as_posix()}` on {generated} by "
        "`build_report.py`.",
        "",
    ]
    return lines


def _build_degraded_block(report: dict) -> List[str]:
    if not report.get("degraded"):
        return []
    reasons = report.get("degraded_reasons") or []
    missing_metrics = report.get("missing_metrics") or []
    missing_contribs = report.get("missing_contributors") or []
    partial = report.get("partial_results") or []

    lines = [
        "> **⚠ Degraded run.** One or more benchmarks failed or were partial. "
        "Treat the headline numbers as lower-bounds and read the appendix "
        "before drawing conclusions.",
        "",
    ]
    if reasons:
        lines.append("**Degradation reasons:**")
        for r in reasons:
            lines.append(f"- {r}")
        lines.append("")
    if missing_metrics:
        lines.append(f"**Missing benchmarks:** {', '.join(missing_metrics)}")
        lines.append("")
    if missing_contribs:
        lines.append(
            f"**Benchmarks with empty contributor lists:** "
            f"{', '.join(missing_contribs)}"
        )
        lines.append("")
    if partial:
        lines.append(f"**Partial benchmarks:** {', '.join(partial)}")
        lines.append("")
    return lines


def _build_executive_summary_placeholder() -> List[str]:
    return [
        "## Executive Summary",
        "",
        "<!-- AGENT FILL: 2-3 sentences answering the headline business "
        "question — what enterprise work CAN and CANNOT this model be "
        "trusted with today? Lead with a deployment verdict (e.g. \"ready "
        "to ship as an L1 helpdesk agent on bounded tool surfaces; not "
        "ready as a customer-facing intake bot\"), then anchor the verdict "
        "in the EGI Score and one specific strength + one specific "
        "weakness from Phase 3. Score percentages are evidence; the "
        "deployment verdict is the finding. Replace this comment AND the "
        "'Pending' line below with the narrative. -->",
        "",
        "_Pending — fill in during analysis._",
        "",
    ]


def _build_egi_table(report: dict) -> List[str]:
    metrics = _egi_metrics(report)
    egi = _egi_score(report)

    lines = [
        "## EGI Score Breakdown",
        "",
        "| Metric | Weight | Score | Verdict |",
        "| --- | ---: | ---: | --- |",
    ]
    for m in M_ORDER:
        bucket = metrics.get(m) or {}
        score = bucket.get("score")
        weight = bucket.get("weight")
        weight_str = f"{weight:.0%}" if weight is not None else "—"
        lines.append(
            f"| **{m}. {M_FULL_NAMES[m]}** "
            f"| {weight_str} | {_fmt_score(score)} | {_verdict(score)} |"
        )
    lines.append(
        f"| **EGI Score** | | **{_fmt_score(egi)}** | **{_verdict(egi)}** |"
    )
    lines.append("")

    missing = _missing_egi_metrics(report)
    if missing:
        lines.append(
            f"_M-buckets with no contributors in this run "
            f"(skipped, not zeroed):_ **{', '.join(missing)}**"
        )
        lines.append("")
    return lines


def _build_domain_table(report: dict) -> List[str]:
    domains = report.get("domain_scores") or {}
    rows: List[Tuple[str, dict]] = list(domains.items())
    # Strongest first; benchmarks without a numeric score sink to the bottom.
    rows.sort(
        key=lambda r: (r[1].get("score") if r[1].get("score") is not None else -1),
        reverse=True,
    )

    lines = [
        "## Per-Benchmark Scores",
        "",
        "| Benchmark | Score | Status | Runtime | Verdict |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for name, detail in rows:
        score = detail.get("score")
        status = detail.get("status", "?")
        if detail.get("partial_reason"):
            status = "partial"
        runtime = _fmt_runtime(detail.get("runtime_seconds"), compact=True)
        lines.append(
            f"| {name} | {_fmt_score(score)} | {status} | {runtime} | "
            f"{_verdict(score)} |"
        )
    lines.append("")

    notes = []
    for name, detail in rows:
        if detail.get("error_message"):
            notes.append(f"- **{name}** error: {detail['error_message']}")
        elif detail.get("partial_reason"):
            notes.append(f"- **{name}** partial: {detail['partial_reason']}")
        for note in detail.get("notes") or []:
            notes.append(f"- **{name}** note: {note}")
    if notes:
        lines.append("**Per-benchmark notes:**")
        lines.extend(notes)
        lines.append("")
    return lines


def _build_per_bucket_diagnosis(report: dict) -> List[str]:
    metrics = _egi_metrics(report)

    lines = [
        "## Per-Bucket Diagnosis",
        "",
        "Every contributor to every M-bucket, sorted from highest to lowest. "
        "Wide-spread buckets (>40 points between top and bottom) are flagged — "
        "in those cases the bucket mean is a misleading average and the agent "
        "should inspect the extremes individually.",
        "",
    ]
    for m in M_ORDER:
        bucket = metrics.get(m) or {}
        score = bucket.get("score")
        weight = bucket.get("weight")
        weight_str = f"{weight:.0%}" if weight is not None else "—"
        contributors = list(bucket.get("contributors") or [])
        contributors.sort(
            key=lambda c: (c.get("value") if c.get("value") is not None else -1),
            reverse=True,
        )

        lines.append(
            f"### {m}. {M_FULL_NAMES[m]} — {_fmt_score(score)} "
            f"({_verdict(score)}, weight {weight_str})"
        )
        lines.append("")

        if not contributors:
            lines.append("_No contributors in this run — bucket skipped._")
            lines.append("")
            continue

        lines.append("| Sub-score | Source | Value |")
        lines.append("| ---       | ---    | ---:  |")
        for c in contributors:
            value = c.get("value")
            value_str = f"{value:.2f}" if value is not None else "—"
            lines.append(
                f"| `{c.get('name', '?')}` "
                f"| {c.get('source', '?')} "
                f"| {value_str} |"
            )
        lines.append("")

        values = [c.get("value") for c in contributors if c.get("value") is not None]
        if len(values) >= 2:
            spread = max(values) - min(values)
            if spread > WIDE_SPREAD_THRESHOLD:
                top = max(contributors, key=lambda c: c.get("value") or -1)
                bot = min(contributors, key=lambda c: c.get("value") or 101)
                lines.append(
                    f"> **Wide spread ({spread:.1f} points).** Top: "
                    f"`{top['name']}` ({top['source']}, {top['value']:.1f}). "
                    f"Bottom: `{bot['name']}` ({bot['source']}, "
                    f"{bot['value']:.1f}). The bucket mean hides this — "
                    f"diagnose at the contributor level."
                )
                lines.append("")
    return lines


def _build_strengths_weaknesses_placeholder() -> List[str]:
    return [
        "## Capability Assessment",
        "",
        "<!-- AGENT FILL: 3-5 bullets each. Hard rule: every bullet leads with "
        "a concrete enterprise scenario (a real role or workflow this model "
        "would be deployed in), then justifies it with sub-score evidence "
        "TRANSLATED INTO THE WORKFLOW CONSEQUENCE. Wrong: \"Strong on M2 "
        "(78%)\". Right: \"Reliable as an L1 helpdesk-style tool-calling "
        "agent on bounded tool surfaces (Benchforce hospital_finished_ratio "
        "= 100%, MCPEval airbnb flex avg = 79.5% — the agent reliably "
        "completes multi-step tool flows without abandoning).\" Use the "
        "Enterprise Role Mapping in SKILL.md to translate benchmarks into "
        "roles. Pull from Phase 3 of the analysis. Replace this comment "
        "AND the 'Pending' lines below. In comparison mode, use headings "
        "'Capabilities Gained' / 'Capabilities Lost' / 'Capabilities Now "
        "Stable'. -->",
        "",
        "**Strengths — what this model can do reliably in enterprise workflows**",
        "",
        "- _Pending — fill in during analysis._",
        "",
        "**Weaknesses — workflows this model cannot be trusted with today**",
        "",
        "- _Pending — fill in during analysis._",
        "",
    ]


def _build_recommendations_placeholder() -> List[str]:
    return [
        "## Deployment Recommendations",
        "",
        "<!-- AGENT FILL: at most 5 items total across the three categories "
        "below. Each item leads with a real enterprise use case (NOT a "
        "metric to lift). 'Ship now' items must name specific guardrails "
        "(citation-required output, restricted tool registry, confidence "
        "threshold + human escalation, etc.). 'Defer' items must "
        "distinguish 'needs a stronger model' from 'needs engineering "
        "around this model'. 'Do not deploy' items must point to the "
        "sub-score patterns that imply unacceptable business risk and "
        "suggest a better path. Optional 6th-bullet 'Model Improvement' "
        "exception only when the user owns the model — frame as "
        "\"investing in capability X unlocks use case Y\", never as "
        "\"lift score Z\". Use the playbook for cross-cutting deployment "
        "patterns. Replace this comment AND the 'Pending' lines below. -->",
        "",
        "**Ship now (with these guardrails)**",
        "",
        "1. _Pending — fill in during analysis._",
        "",
        "**Defer until [model upgrade / scaffold] is in place**",
        "",
        "1. _Pending — fill in during analysis._",
        "",
        "**Do not deploy**",
        "",
        "1. _Pending — fill in during analysis._",
        "",
    ]


def _build_charts_section(
    source: Path,
    *,
    chart_status: str,
) -> List[str]:
    """Auto-link the charts script's outputs if they already exist.

    ``chart_status`` is one of: ``"rendered"``, ``"skipped"``, ``"failed"``.
    It controls the message shown when no chart files are found on disk.
    """
    base = source.stem
    charts_dir = source.parent / "charts" / base
    rel_charts_dir = Path("..") / charts_dir.relative_to(source.parent)

    existing = [
        (rel_charts_dir / fname, label)
        for fname, label in CHART_FILES
        if (charts_dir / fname).exists()
    ]

    lines = ["## Charts", ""]
    if existing:
        lines.append(
            f"_Linked from `{charts_dir.as_posix()}/`. "
            "Regenerate with `scripts/render_charts.py`._"
        )
        lines.append("")
        for path, label in existing:
            lines.append(f"### {label}")
            lines.append("")
            lines.append(f"![{label}]({path.as_posix()})")
            lines.append("")
    elif chart_status == "skipped":
        lines.append(
            "_Charts intentionally skipped (`--no-render-charts`). Re-run "
            "without that flag, or call `scripts/render_charts.py` manually._"
        )
        lines.append("")
    elif chart_status == "failed":
        lines.append(
            "_Could not render charts. The most common cause is `matplotlib` "
            "missing from the active environment. Install with "
            "`uv pip install matplotlib`, then rerun `build_report.py --force` "
            "to populate this section._"
        )
        lines.append("")
    else:
        lines.append(
            "_No charts generated for this run; rerun with "
            "`scripts/render_charts.py` to populate this section._"
        )
        lines.append("")
    return lines


def _build_appendix_subscores(report: dict) -> List[str]:
    domains = report.get("domain_scores") or {}
    lines = [
        "## Appendix: Per-Benchmark Sub-Scores",
        "",
        "Every raw sub-score emitted by every benchmark, exactly as written "
        "to the JSON. Use this when a contributor in the diagnosis section "
        "needs to be cross-referenced against its source benchmark.",
        "",
    ]
    for name in sorted(domains):
        detail = domains[name]
        score = detail.get("score")
        sub_scores = detail.get("sub_scores") or {}
        lines.append(f"### {name} — {_fmt_score(score)}")
        lines.append("")
        if not sub_scores:
            lines.append("_No sub-scores emitted._")
            lines.append("")
            continue
        lines.append("| Sub-score | Value |")
        lines.append("| ---       | ---:  |")
        for k in sorted(sub_scores):
            v = sub_scores[k]
            if isinstance(v, float):
                v_str = f"{v:.2f}"
            else:
                v_str = str(v)
            lines.append(f"| `{k}` | {v_str} |")
        lines.append("")
    return lines


def _build_appendix_metadata(report: dict, source: Path) -> List[str]:
    lines = [
        "## Appendix: Run Metadata",
        "",
        f"- **Source report:** `{source.as_posix()}`",
        f"- **Model:** `{report.get('model', 'n/a')}`",
        f"- **Mode:** `{report.get('mode', 'n/a')}`",
        f"- **Run kind:** `{report.get('run_kind', 'n/a')}` "
        "(`run` = fresh execution; `rescore` = re-aggregated from cached outputs)",
        f"- **Timestamp:** {_fmt_iso_to_human(report.get('timestamp'))}",
        f"- **Total runtime:** {_fmt_runtime(report.get('total_runtime_seconds'))}",
        f"- **Degraded:** {bool(report.get('degraded'))}",
    ]
    weights = report.get("weights")
    if weights:
        weight_str = ", ".join(f"{k}={v}" for k, v in sorted(weights.items()))
        lines.append(f"- **Per-benchmark aggregation weights:** {weight_str}")
    lines.append("")
    lines.append(
        "Routing of every sub-score to its M-bucket is documented in "
        "[`docs/scoring.md`](../../docs/scoring.md) at the repo root."
    )
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def build_markdown(
    report: dict,
    source: Path,
    *,
    chart_status: str = "rendered",
) -> str:
    sections: List[List[str]] = [
        _build_header(report, source),
        _build_degraded_block(report),
        _build_executive_summary_placeholder(),
        _build_egi_table(report),
        _build_domain_table(report),
        _build_per_bucket_diagnosis(report),
        _build_strengths_weaknesses_placeholder(),
        _build_recommendations_placeholder(),
        _build_charts_section(source, chart_status=chart_status),
        _build_appendix_subscores(report),
        _build_appendix_metadata(report, source),
    ]
    return "\n".join(line for section in sections for line in section).rstrip() + "\n"


def _render_charts(
    source: Path,
    *,
    compare: Optional[Path] = None,
) -> str:
    """Invoke render_charts.py via subprocess. Returns ``"rendered"`` on
    success and ``"failed"`` otherwise (so the markdown build can continue
    with a clear hint instead of crashing the whole pipeline)."""
    script = Path(__file__).parent / "render_charts.py"
    cmd = [sys.executable, str(script), "--report", str(source)]
    if compare is not None:
        cmd += ["--compare", str(compare)]
    print(f"Rendering charts: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        print(f"warning: failed to invoke {script.name}: {exc}", file=sys.stderr)
        return "failed"
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(
            f"warning: chart rendering failed (exit {result.returncode}). "
            "Continuing without charts.",
            file=sys.stderr,
        )
        if result.stderr.strip():
            print(result.stderr.rstrip(), file=sys.stderr)
        return "failed"
    return "rendered"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Path to the aggregate JSON report to summarize.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output markdown path. "
        "Defaults to <report_dir>/analysis/<report_stem>.md.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="Optional baseline aggregate JSON to overlay in the rendered "
        "charts (passed through to render_charts.py).",
    )
    parser.add_argument(
        "--no-render-charts",
        dest="render_charts",
        action="store_false",
        help="Do not auto-render charts via render_charts.py. By default the "
        "builder renders the radar / bars / contributors PNGs first and "
        "links them inline in the markdown.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.set_defaults(render_charts=True)
    args = parser.parse_args()

    if not args.report.exists():
        print(f"error: report not found: {args.report}", file=sys.stderr)
        return 2

    out_md = args.out or (args.report.parent / "analysis" / f"{args.report.stem}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)

    if out_md.exists() and not args.force:
        print(
            f"error: {out_md} already exists. Pass --force to overwrite, or "
            f"--out <path> to write elsewhere.",
            file=sys.stderr,
        )
        return 2

    with args.report.open("r") as f:
        report = json.load(f)

    if args.render_charts:
        chart_status = _render_charts(args.report, compare=args.compare)
    else:
        chart_status = "skipped"

    markdown = build_markdown(report, args.report, chart_status=chart_status)
    out_md.write_text(markdown)
    print(f"Wrote: {out_md}")
    print(
        "\nNext step: open the file and replace each `<!-- AGENT FILL: ... -->` "
        "block (and its `Pending` line) with the narrative from your analysis."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
