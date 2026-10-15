#!/usr/bin/env python3
"""
Run PersonaBench against an OpenAI-compatible gateway endpoint.

This wrapper:
1) configures OPENAI_BASE_URL / OPENAI_API_BASE
2) runs retrieval + generation
3) runs statistical evaluation
4) writes a human-readable markdown report with run duration
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

# Add current directory to path for imports.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from personabench.utils.shared_args import add_shared_arguments
from personabench.utils.utils import setup_logger, set_random_seed
from scripts.evaluation import eval as eval_script
from scripts.evaluation import retrieval_and_generation


def _format_seconds(total_seconds):
    seconds = int(round(total_seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _collect_result_summary(result_dir):
    result_paths = sorted(glob.glob(os.path.join(result_dir, "result_noise_*.json")))
    settings = {}
    total_questions = 0
    missing_predictions = 0

    for result_path in result_paths:
        with open(result_path, "r") as f:
            result_data = json.load(f)
        for setting in result_data:
            setting_name = setting["Model"]
            results = setting.get("Results", [])
            total_questions += len(results)
            missing_predictions += sum(1 for row in results if not row.get("prediction"))
            settings.setdefault(setting_name, 0)
            settings[setting_name] += len(results)

    return {
        "result_paths": result_paths,
        "settings": settings,
        "total_questions": total_questions,
        "missing_predictions": missing_predictions,
    }


def _render_report(args, result_dir, started_at_utc, ended_at_utc, duration_seconds):
    summary = _collect_result_summary(result_dir)
    statistics_path = os.path.join(result_dir, "statistics_all_noises.json")
    table_path = os.path.join(result_dir, "table.txt")
    plots = [
        os.path.join(result_dir, "e2e.jpg"),
        os.path.join(result_dir, "retrival.jpg"),
        os.path.join(result_dir, "radar_all.jpg"),
    ]

    lines = [
        "# PersonaBench Evaluation Report",
        "",
        "## Run Metadata",
        f"- UTC start time: `{started_at_utc.isoformat()}`",
        f"- UTC end time: `{ended_at_utc.isoformat()}`",
        f"- Duration: `{_format_seconds(duration_seconds)}` ({duration_seconds:.2f} seconds)",
        f"- Gateway endpoint: `{args.openai_base_url}`",
        f"- Models: `{args.base_models}`",
        f"- Retrievers: `{args.retrievers}`",
        f"- Noise levels: `{args.test_noises}`",
        f"- Communities: `{args.test_community_ids}`",
        f"- People per community: `{args.num_people}`",
        "",
        "## Recorded Results",
        f"- Result files: `{len(summary['result_paths'])}`",
        f"- Total question records: `{summary['total_questions']}`",
        f"- Missing predictions: `{summary['missing_predictions']}`",
        "",
        "### Records by Model+Retriever",
    ]

    for setting_name in sorted(summary["settings"]):
        lines.append(f"- `{setting_name}`: `{summary['settings'][setting_name]}` records")

    lines.extend([
        "",
        "## Artifacts",
        f"- Raw per-noise outputs: `{result_dir}`",
        f"- Statistics JSON: `{statistics_path}`",
        f"- Human-readable table: `{table_path}`",
    ])

    for plot_path in plots:
        if os.path.exists(plot_path):
            lines.append(f"- Plot: `{plot_path}`")

    lines.extend([
        "",
        "## Verification",
        "- The run is considered complete when `Missing predictions` is `0` and all expected noise files exist.",
    ])

    report_path = os.path.join(result_dir, args.report_name)
    with open(report_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser = add_shared_arguments(parser)
    parser.add_argument("--log_dir", type=str, default="logs", help="Path to save eval results.")
    parser.add_argument(
        "--test_community_ids",
        type=str,
        default="community_0,community_1",
        help="Comma-separated list of community ids to test",
    )
    parser.add_argument(
        "--num_people",
        type=int,
        default=3,
        help="Number of individuals to test in each community",
    )
    parser.add_argument(
        "--base_models",
        type=str,
        default="gpt-4.1-nano",
        help="Comma-separated list of base models to evaluate",
    )
    parser.add_argument(
        "--retrievers",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Comma-separated list of retriever models to evaluate",
    )
    parser.add_argument("--num_chunks", type=int, default=5, help="Number of chunks for retrieval tasks")
    parser.add_argument(
        "--test_noises",
        type=str,
        default="0.0",
        help="Comma-separated list of noise levels for testing",
    )
    parser.add_argument(
        "--openai_base_url",
        type=str,
        default=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "http://localhost:8008/v1",
        help="OpenAI-compatible endpoint, e.g. http://localhost:8008/v1",
    )
    parser.add_argument(
        "--report_name",
        type=str,
        default="benchmark_report.md",
        help="Markdown report filename generated under the result directory.",
    )
    parser.add_argument(
        "--no_radar_normalization",
        action="store_true",
        help="Whether normalize results before drawing radar chart.",
    )
    parser.add_argument(
        "--radar_model",
        type=str,
        default=None,
        help="Optional model name to highlight in the radar chart filename.",
    )

    args = parser.parse_args()
    setup_logger(args.verbose)
    set_random_seed(args.seed)

    # Configure gateway routing for both old/new OpenAI SDK env var conventions.
    os.environ["OPENAI_API_KEY"] = args.api_key or os.getenv("OPENAI_API_KEY") or "dummy"
    os.environ["OPENAI_BASE_URL"] = args.openai_base_url
    os.environ["OPENAI_API_BASE"] = args.openai_base_url
    args.api_key = os.environ["OPENAI_API_KEY"]

    started_at_utc = datetime.now(timezone.utc)
    start_monotonic = time.perf_counter()

    retrieval_and_generation.retrieval_and_generation(args)
    eval_script.eval(args)

    duration_seconds = time.perf_counter() - start_monotonic
    ended_at_utc = datetime.now(timezone.utc)

    dataset_name = args.data_dir.split("/")[-1]
    result_dir = os.path.join(args.log_dir, dataset_name, f"results_all_community_chunk_{args.num_chunks}")
    report_path = _render_report(args, result_dir, started_at_utc, ended_at_utc, duration_seconds)

    print("PersonaBench evaluation finished.")
    print(f"Results directory: {result_dir}")
    print(f"Human-readable report: {report_path}")
