#!/usr/bin/env python3
"""Render charts for an EGI-Bench aggregate report.

Reads an aggregate JSON report produced by ``egi-bench run`` (or
``egi-bench report --rescore``) and writes three PNGs:

  - ``m1_m6_radar.png``      — six-spoke radar of M1-M6 vs a 50% reference.
  - ``domain_bars.png``      — horizontal bars of per-benchmark scores,
                                color-banded by verdict.
  - ``m_contributors.png``   — strip plot of every contributor in every
                                M-bucket; highlights spread within a bucket.

Optional ``--compare path/to/baseline.json`` overlays a baseline run on
the radar and bars.

The script is intentionally self-contained: only depends on matplotlib +
stdlib, so it works against any aggregate report (current
``egi_score`` / ``egi_metrics`` schema *or* the legacy
``enterprise_readiness_score`` / ``enterprise_metrics`` schema produced
by older runs).

Usage:
    # one-time install (matplotlib is NOT in the root .venv)
    uv pip install matplotlib

    python .claude/skills/egi-bench-analyze-results/scripts/render_charts.py \\
        --report results_aggregated/<model>_<mode>_<timestamp>.json

    python .claude/skills/egi-bench-analyze-results/scripts/render_charts.py \\
        --report results_aggregated/run_after.json \\
        --compare results_aggregated/run_before.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
except ImportError:  # pragma: no cover - friendly install hint
    sys.exit(
        "matplotlib is required. Install it with:\n"
        "  uv pip install matplotlib\n"
        "(matplotlib is not part of the root EGI-Bench venv.)"
    )


M_ORDER = ("M1", "M2", "M3", "M4", "M5", "M6")
M_LABELS = {
    "M1": "M1\nTask\nOutcome",
    "M2": "M2\nTool\nActioning",
    "M3": "M3\nPlanning &\nWorkflow",
    "M4": "M4\nRetrieval &\nGrounding",
    "M5": "M5\nSafety &\nAbstention",
    "M6": "M6\nEng. &\nMaintain.",
}

# Verdict bands. Calibrated for current frontier-model performance on
# enterprise tasks: SOTA typically lands in Mixed, so Strong / Production are
# reserved for genuinely exceptional scores. Kept in lockstep with
# build_report.py::VERDICT_BANDS and SKILL.md.
VERDICT_BANDS = [
    (0, 30, "Failing", "#c0392b"),
    (30, 50, "Weak", "#e67e22"),
    (50, 65, "Mixed", "#f1c40f"),
    (65, 80, "Strong", "#27ae60"),
    (80, 100.001, "Production", "#2980b9"),
]


# ---------------------------------------------------------------------------
# Report loading (handles current + legacy schemas)
# ---------------------------------------------------------------------------


def _load_report(path: Path) -> dict:
    with path.open("r") as f:
        report = json.load(f)
    return report


def _egi_score(report: dict) -> Optional[float]:
    val = report.get("egi_score")
    if val is None:
        # Legacy reports name it differently.
        val = report.get("enterprise_readiness_score")
    if val is None:
        val = report.get("overall_score")
    return val


def _egi_metrics(report: dict) -> Dict[str, dict]:
    metrics = report.get("egi_metrics") or report.get("enterprise_metrics") or {}
    return metrics


def _label(report: dict, fallback: str) -> str:
    model = report.get("model") or "unknown-model"
    mode = report.get("mode") or "unknown-mode"
    return f"{model} ({mode})" if model and mode else fallback


def _band(score: float) -> Tuple[str, str]:
    for lo, hi, name, color in VERDICT_BANDS:
        if lo <= score < hi:
            return name, color
    return "Unknown", "#7f8c8d"


# ---------------------------------------------------------------------------
# Chart 1: M1-M6 radar
# ---------------------------------------------------------------------------


def render_radar(
    primary: dict,
    out_path: Path,
    compare: Optional[dict] = None,
) -> None:
    metrics = _egi_metrics(primary)
    primary_scores = [
        (metrics.get(m) or {}).get("score") or 0.0 for m in M_ORDER
    ]

    angles = [2 * math.pi * i / len(M_ORDER) for i in range(len(M_ORDER))]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8.0, 8.0), subplot_kw={"projection": "polar"})
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([M_LABELS[m] for m in M_ORDER], fontsize=10)

    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color="#666")

    # Reference circle at 50.
    ax.plot(
        angles,
        [50] * len(angles),
        color="#bbb",
        linewidth=1,
        linestyle="--",
        label="50% reference",
    )

    primary_label = _label(primary, "primary run")
    primary_values = primary_scores + primary_scores[:1]
    ax.plot(angles, primary_values, color="#2980b9", linewidth=2.0, label=primary_label)
    ax.fill(angles, primary_values, color="#2980b9", alpha=0.20)

    if compare is not None:
        compare_metrics = _egi_metrics(compare)
        compare_scores = [
            (compare_metrics.get(m) or {}).get("score") or 0.0 for m in M_ORDER
        ]
        compare_label = _label(compare, "baseline")
        compare_values = compare_scores + compare_scores[:1]
        ax.plot(
            angles,
            compare_values,
            color="#e67e22",
            linewidth=2.0,
            linestyle="--",
            label=compare_label,
        )
        ax.fill(angles, compare_values, color="#e67e22", alpha=0.10)

    egi = _egi_score(primary)
    egi_str = f"{egi:.1f}%" if egi is not None else "n/a"
    title = f"EGI Score breakdown — {primary_label} (EGI = {egi_str})"
    if compare is not None:
        baseline_egi = _egi_score(compare)
        baseline_str = f"{baseline_egi:.1f}%" if baseline_egi is not None else "n/a"
        title = (
            f"EGI Score breakdown — {primary_label} ({egi_str}) "
            f"vs {_label(compare, 'baseline')} ({baseline_str})"
        )
    ax.set_title(title, fontsize=11, pad=22)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.05), fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 2: per-benchmark horizontal bars
# ---------------------------------------------------------------------------


def render_domain_bars(
    primary: dict,
    out_path: Path,
    compare: Optional[dict] = None,
) -> None:
    domains = primary.get("domain_scores") or {}
    rows: List[Tuple[str, float, Optional[float]]] = []
    compare_domains = (compare or {}).get("domain_scores") or {}

    for name, detail in domains.items():
        score = detail.get("score")
        if score is None:
            continue
        baseline_score = None
        if compare_domains:
            baseline_detail = compare_domains.get(name) or {}
            baseline_score = baseline_detail.get("score")
        rows.append((name, float(score), baseline_score))

    # Sort ascending. matplotlib's default barh axis puts y=0 at the bottom,
    # so the weakest benchmark ends up at the bottom of the chart and the
    # strongest at the top — the natural reading order.
    rows.sort(key=lambda r: r[1])

    if not rows:
        return

    fig, ax = plt.subplots(figsize=(9.0, 0.55 * len(rows) + 1.5))
    names = [r[0] for r in rows]
    scores = [r[1] for r in rows]
    colors = [_band(s)[1] for s in scores]

    y_positions = list(range(len(rows)))
    bar_height = 0.55 if compare is None else 0.36

    bars = ax.barh(
        y_positions,
        scores,
        color=colors,
        height=bar_height,
        edgecolor="white",
        label="primary",
    )

    if compare is not None:
        offsets = [y + bar_height + 0.04 for y in y_positions]
        baseline_scores = [r[2] if r[2] is not None else 0.0 for r in rows]
        ax.barh(
            offsets,
            baseline_scores,
            color="#7f8c8d",
            height=bar_height,
            alpha=0.55,
            edgecolor="white",
            label="baseline",
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(names, fontsize=10)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Score (0-100)")
    ax.set_axisbelow(True)
    ax.grid(axis="x", linestyle=":", color="#aaa", alpha=0.6)

    for bar, score in zip(bars, scores):
        ax.text(
            min(score + 1.5, 99),
            bar.get_y() + bar.get_height() / 2,
            f"{score:.1f}",
            va="center",
            fontsize=9,
        )

    legend_handles = [
        Patch(facecolor=color, label=name) for _, _, name, color in VERDICT_BANDS
    ]
    if compare is not None:
        legend_handles.append(Patch(facecolor="#7f8c8d", alpha=0.55, label="baseline"))
    ax.legend(handles=legend_handles, loc="lower right", fontsize=8, frameon=True)

    title = f"Per-benchmark scores — {_label(primary, 'primary run')}"
    if compare is not None:
        title += f" vs {_label(compare, 'baseline')}"
    ax.set_title(title, fontsize=11)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 3: M-bucket contributor strip plot
# ---------------------------------------------------------------------------


def render_contributors(primary: dict, out_path: Path) -> None:
    metrics = _egi_metrics(primary)

    fig, ax = plt.subplots(figsize=(9.0, 6.0))

    y_positions = list(range(len(M_ORDER)))
    for y, m in zip(y_positions, M_ORDER):
        bucket = metrics.get(m) or {}
        contributors = bucket.get("contributors") or []
        if not contributors:
            ax.text(
                50, y, "(no contributors)",
                fontsize=9, color="#888", ha="center", va="center", style="italic",
            )
            continue

        values = [c.get("value") for c in contributors if c.get("value") is not None]
        sources = [c.get("source", "?") for c in contributors if c.get("value") is not None]
        names = [c.get("name", "?") for c in contributors if c.get("value") is not None]

        # one dot per contributor, color by source benchmark
        source_colors = _color_by_source(sources)
        ax.scatter(
            values,
            [y] * len(values),
            s=70,
            c=source_colors,
            edgecolors="white",
            linewidths=0.6,
            alpha=0.85,
            zorder=3,
        )

        # mean marker
        mean = sum(values) / len(values)
        ax.scatter([mean], [y], marker="|", s=400, color="black", zorder=4)
        ax.text(
            mean, y - 0.30,
            f"mean {mean:.1f}",
            fontsize=8, color="#333", ha="center",
        )

        # call out min/max names if spread is wide
        if max(values) - min(values) > 40:
            i_min = values.index(min(values))
            i_max = values.index(max(values))
            ax.annotate(
                f"{names[i_min]} ({sources[i_min]})",
                xy=(values[i_min], y),
                xytext=(values[i_min] + 1.5, y + 0.30),
                fontsize=7, color="#c0392b",
            )
            ax.annotate(
                f"{names[i_max]} ({sources[i_max]})",
                xy=(values[i_max], y),
                xytext=(values[i_max] - 1.5, y + 0.30),
                fontsize=7, color="#27ae60", ha="right",
            )

    ax.set_yticks(y_positions)
    ax.set_yticklabels([m for m in M_ORDER], fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Sub-score value (0-100)")
    ax.grid(axis="x", linestyle=":", color="#aaa", alpha=0.6)
    ax.set_axisbelow(True)
    ax.set_title(
        f"M1-M6 contributor distribution — {_label(primary, 'primary run')}\n"
        "(black bar = bucket mean; min/max names shown when spread > 40 points)",
        fontsize=10,
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _color_by_source(sources: List[str]) -> List[str]:
    palette = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]
    seen: Dict[str, str] = {}
    out: List[str] = []
    for src in sources:
        if src not in seen:
            seen[src] = palette[len(seen) % len(palette)]
        out.append(seen[src])
    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Path to the aggregate JSON report to chart.",
    )
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="Optional baseline report to overlay on the radar and bar charts.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <report_dir>/charts/<report_stem>/.",
    )
    args = parser.parse_args()

    if not args.report.exists():
        print(f"error: report not found: {args.report}", file=sys.stderr)
        return 2

    primary = _load_report(args.report)
    compare = _load_report(args.compare) if args.compare else None

    out_dir = args.out_dir or (args.report.parent / "charts" / args.report.stem)
    out_dir.mkdir(parents=True, exist_ok=True)

    radar_path = out_dir / "m1_m6_radar.png"
    bars_path = out_dir / "domain_bars.png"
    contributors_path = out_dir / "m_contributors.png"

    render_radar(primary, radar_path, compare=compare)
    render_domain_bars(primary, bars_path, compare=compare)
    render_contributors(primary, contributors_path)

    print(f"Wrote: {radar_path}")
    print(f"Wrote: {bars_path}")
    print(f"Wrote: {contributors_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
