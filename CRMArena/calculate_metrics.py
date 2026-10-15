#!/usr/bin/env python3
"""
Calculate CRMArena metrics from result files.

This script aggregates results from individual task runs and computes
the metrics shown in the paper (NCR, HTU, TCU, NED, PVI, KQA, TII, BRI, ALL).
"""

import json
import glob
import os
from collections import defaultdict
from typing import Dict, List

# Task type to acronym mapping (from the paper)
TASK_ACRONYMS = {
    "case_routing": "NCR",  # Case Routing
    "handle_time": "HTU",  # Handle Time Understanding
    "transfer_count": "TCU",  # Transfer Count Understanding
    "named_entity_disambiguation": "NED",  # Named Entity Disambiguation
    "policy_violation_identification": "PVI",  # Policy Violation Identification
    "knowledge_qa": "KQA",  # Knowledge QA
    "top_issue_identification": "TII",  # Top Issue Identification
    "best_region_identification": "BRI",  # Best Region Identification
    "monthly_trend_analysis": "MTA",  # Monthly Trend Analysis (if exists)
}


def extract_reward_value(reward):
    """
    Extract a single reward value from different reward formats.

    Args:
        reward: Can be:
            - int/float: direct reward (0 or 1)
            - dict with 'em' key: exact match score
            - dict with 'f1' key: F1 score

    Returns:
        float: The reward value (0-1)
    """
    if isinstance(reward, (int, float)):
        return float(reward)
    elif isinstance(reward, dict):
        # For fuzzy match, use EM (exact match) as the primary metric
        # but could also use F1, BLEU, or ROUGE
        if 'em' in reward:
            return 1.0 if reward['em'] else 0.0
        elif 'f1' in reward:
            return reward['f1']
    return 0.0


def calculate_task_accuracy(results: List[Dict]) -> float:
    """
    Calculate accuracy for a specific task.

    Args:
        results: List of result dictionaries for a task

    Returns:
        float: Accuracy (0-1)
    """
    if not results:
        return 0.0

    total_reward = sum(extract_reward_value(r['reward']) for r in results)
    return total_reward / len(results)


def aggregate_results(result_dir: str, model_name: str = None, strategy: str = None) -> Dict[str, float]:
    """
    Aggregate results from a directory.

    Args:
        result_dir: Directory containing result JSON files
        model_name: Optional model name filter (e.g., "gpt-5-mini")
        strategy: Optional strategy filter (e.g., "tool_call")

    Returns:
        Dict mapping task acronyms to accuracy scores
    """
    # Find all result files. Mirror the sanitization that ``run_tasks.py``
    # applies when building ``ckpt_path``, otherwise a provider-prefixed
    # ``model_name`` like ``vertex/gemini-2.5-flash`` would glob the wrong
    # subdirectory (``results_vertex/gemini-2.5-flash_…``) instead of the flat
    # filename actually written to disk.
    if model_name and strategy:
        safe_model = model_name.replace("/", "_").replace(":", "_")
        pattern = f"{result_dir}/results_{safe_model}_{strategy}_*.json"
    else:
        pattern = f"{result_dir}/results_*.json"

    result_files = glob.glob(pattern)

    if not result_files:
        print(f"No result files found matching pattern: {pattern}")
        return {}

    # Group results by task type
    task_results = defaultdict(list)

    for result_file in result_files:
        with open(result_file, 'r') as f:
            results = json.load(f)

        for result in results:
            task_type = result['task_type']
            task_results[task_type].append(result)

    # Calculate accuracy for each task
    metrics = {}
    for task_type, results in task_results.items():
        accuracy = calculate_task_accuracy(results)
        acronym = TASK_ACRONYMS.get(task_type, task_type.upper())
        metrics[acronym] = accuracy

    # Calculate overall average (ALL)
    if metrics:
        metrics['ALL'] = sum(metrics.values()) / len(metrics)

    return metrics


def print_metrics_table(metrics: Dict[str, float], model_name: str = "Model"):
    """
    Print metrics in a formatted table.

    Args:
        metrics: Dictionary of task acronyms to accuracy scores
        model_name: Name of the model for display
    """
    print(f"\n{'='*60}")
    print(f"Results for: {model_name}")
    print(f"{'='*60}")

    # Sort by task acronym (but put ALL at the end)
    sorted_metrics = sorted(
        [(k, v) for k, v in metrics.items() if k != 'ALL'],
        key=lambda x: x[0]
    )

    # Print individual tasks
    for acronym, accuracy in sorted_metrics:
        print(f"{acronym:10s}: {accuracy:6.2%}")

    # Print overall
    if 'ALL' in metrics:
        print(f"{'-'*60}")
        print(f"{'ALL':10s}: {metrics['ALL']:6.2%}")

    print(f"{'='*60}\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Calculate CRMArena metrics from result files"
    )
    parser.add_argument(
        "--result_dir",
        type=str,
        default="results/original/tool_call_openai",
        help="Directory containing result JSON files"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name to filter (e.g., gpt-5-mini)"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Strategy to filter (e.g., tool_call)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file to save metrics"
    )

    args = parser.parse_args()

    # Calculate metrics
    metrics = aggregate_results(args.result_dir, args.model, args.strategy)

    if not metrics:
        print("No results found!")
        return

    # Print table
    model_display = args.model or "All models"
    print_metrics_table(metrics, model_display)

    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"Metrics saved to: {args.output}")

    # Print raw metrics for easy copying
    print("Raw metrics (for spreadsheet):")
    sorted_keys = sorted([k for k in metrics.keys() if k != 'ALL'])
    if 'ALL' in metrics:
        sorted_keys.append('ALL')
    print("\t".join(sorted_keys))
    print("\t".join([f"{metrics[k]:.4f}" for k in sorted_keys]))


if __name__ == "__main__":
    main()
