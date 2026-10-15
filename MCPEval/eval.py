#!/usr/bin/env python3
"""
MCPEval - Evaluation entry point.

Runs LLM evaluation against MCP tool-use tasks for airbnb, yfinance, or national_parks domains.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure mcpeval package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcpeval.evaluate import evaluate_performance
from mcpeval.synthesis.utils import load_tasks_from_jsonl
from mcpeval.utils.cli import setup_colored_logging

setup_colored_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

# Domain configurations: tasks file, MCP server, args, env
DOMAIN_CONFIG = {
    "airbnb": {
        "tasks": "data/airbnb/evaluation_tasks_verified.jsonl",
        "prompt": "benchmarks/airbnb/evaluation_prompt.json",
        "servers": ["@openbnb/mcp-server-airbnb"],
        "server_args": [["--ignore-robots-txt"]],
        "server_envs": [None],
    },
    "yfinance": {
        "tasks": "data/yfinance/evaluation_tasks_verified.jsonl",
        "prompt": "benchmarks/yfinance/evaluation_prompt.json",
        "servers": ["mcp_servers/yfinance/server.py"],
        "server_args": [[]],
        "server_envs": [None],
    },
    "national_parks": {
        "tasks": "data/national_parks/evaluation_tasks_verified.jsonl",
        "prompt": "benchmarks/national_parks/evaluation_prompt.json",
        "servers": ["mcp-server-nationalparks"],
        "server_args": [[]],
        "server_envs": [{"NPS_API_KEY": os.environ.get("NPS_API_KEY", "")}],
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="MCPEval - MCP Tool-Use Evaluation")
    parser.add_argument(
        "--domain",
        required=True,
        choices=list(DOMAIN_CONFIG.keys()),
        help="Evaluation domain",
    )
    parser.add_argument(
        "--model-config",
        required=True,
        help="Path to model configuration JSON file",
    )
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=-1,
        help="Number of tasks to evaluate (-1 for all)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        help="Maximum conversation turns per task",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: results/<domain>_<model>_results.jsonl)",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Override system prompt file (default: domain-specific prompt)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    domain = DOMAIN_CONFIG[args.domain]

    # Load model config
    config_path = Path(args.model_config)
    if not config_path.exists():
        logger.error(f"Model config file not found: {args.model_config}")
        sys.exit(1)
    with open(config_path) as f:
        model_config = json.load(f)

    model_name = model_config.get("model", "unknown")

    # Check API key
    api_key = model_config.get("api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set and no api_key in model config")
        sys.exit(1)

    # Load tasks
    tasks_file = os.path.join(base_dir, domain["tasks"])
    logger.info(f"Loading tasks from {tasks_file}")
    tasks = load_tasks_from_jsonl(tasks_file)
    logger.info(f"Loaded {len(tasks)} tasks")

    if args.num_tasks > 0:
        tasks = tasks[: args.num_tasks]
        logger.info(f"Limiting to {len(tasks)} tasks")

    # Determine output path
    if args.output:
        output_file = args.output
        # ``--output`` may legitimately point inside a not-yet-created subdir
        # (the runner uses ``benchmarks/<domain>/results/unified_<safe>_evaluation.jsonl``).
        # Ensure the parent exists so direct invocations don't crash later.
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    else:
        os.makedirs(os.path.join(base_dir, "results"), exist_ok=True)
        # Sanitize ``model_name`` for filesystem use: provider-prefixed names
        # like ``vertex/gemini-2.5-flash`` would otherwise be interpreted as a
        # subdirectory, and the open() that follows would crash with
        # ``FileNotFoundError``.
        safe_model = model_name.replace("/", "_").replace(":", "_")
        output_file = os.path.join(
            base_dir, "results", f"{args.domain}_{safe_model}_results.jsonl"
        )

    # Determine prompt file
    prompt_file = args.prompt_file or os.path.join(base_dir, domain["prompt"])

    # Resolve server paths (make relative paths absolute)
    server_paths = []
    for s in domain["servers"]:
        if s.endswith(".py"):
            server_paths.append(os.path.join(base_dir, s))
        else:
            server_paths.append(s)

    logger.info(f"Domain: {args.domain}")
    logger.info(f"Model: {model_name}")
    logger.info(f"Tasks: {len(tasks)}")
    logger.info(f"Max turns: {args.max_turns}")
    logger.info(f"Output: {output_file}")
    logger.info(f"Servers: {server_paths}")

    start_time = time.time()

    results = await evaluate_performance(
        tasks=tasks,
        model_name=model_name,
        model_config=model_config,
        server_paths=server_paths,
        server_args_list=domain["server_args"],
        server_envs=domain["server_envs"],
        output_file=output_file,
        max_turns=args.max_turns,
        prompt_file=prompt_file,
    )

    elapsed = time.time() - start_time
    successful = sum(1 for r in results if r.get("success", False))
    total = len(results)
    rate = successful / total * 100 if total > 0 else 0

    print(f"\nEvaluation Summary:")
    print(f"  Domain: {args.domain}")
    print(f"  Model: {model_name}")
    print(f"  Tasks evaluated: {total}")
    print(f"  Successful: {successful}")
    print(f"  Success rate: {rate:.2f}%")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Results: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
