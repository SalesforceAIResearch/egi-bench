#!/usr/bin/env python3
"""
Wrapper script for running Benchforce in text mode via the egi-bench runner.

Generates a text-mode config.yaml, runs the benchmark for a given environment,
and outputs results in a standardized format.

Usage:
    python run_benchforce.py --environment hospital --model gpt-4o-mini \
        --base-url http://localhost:8008/v1 --entries -1
"""

import argparse
import os
import tempfile

import yaml


def generate_config(environment: str, model: str, entries: list, max_turns: int,
                    results_save_path: str = ""):
    """Generate a text-mode config.yaml for Benchforce."""
    config = {
        "debug": True,
        "agent_mode": "text",
        "agent_chat_model": model,
        "agent_chat_provider": None,
        "environment": environment,
        "entries": entries,
        "metrics": ["accuracy"],
        "noises": [],
        "noise_volume": 0,
        "num_threads": 5,
        "max_turns": max_turns,
        "sample_rate": 24000,
        "cutoff_freq": 0,
        "clipping_threshold": 0,
        "drop_probability": 0,
        "chunk_size_ms": 100,
        "snr_db": 0,
        "task_iterations": 1,
        "termination_timer": 600,
        "results_save_path": results_save_path,
        # Voice settings (unused in text mode but parser expects them)
        "agent_tts_model": "eleven_multilingual_v2",
        "agent_tts_voice": "JBFqnCBsd6RMkjVDRZzb",
        "agent_tts_clean_model": "gpt-4o-mini",
        "agent_stt_model": "nova-3",
        "agent_realtime_model": "",
        "agent_realtime_voice": "alloy",
        "client_tts_model": "eleven_multilingual_v2",
        "client_tts_voice": "56AoDkrOh6qfVPDXZ7Pt",
        "client_realtime_model": "",
    }
    return config


def main():
    p = argparse.ArgumentParser(description="Run Benchforce in text mode")
    p.add_argument("--environment", required=True,
                   choices=["hospital", "hr_software"],
                   help="Environment to evaluate")
    p.add_argument("--model", required=True, help="Model name for the agent")
    p.add_argument("--base-url", default="http://localhost:8008/v1",
                   help="OpenAI-compatible API base URL")
    p.add_argument("--api-key", default="dummy", help="API key")
    p.add_argument("--entries", type=int, nargs="+", default=[-1],
                   help="1-based entry numbers to run (-1 for all)")
    p.add_argument("--max-turns", type=int, default=15,
                   help="Max conversation turns per entry")
    p.add_argument("--results-dir", default="results",
                   help="Directory to save results")
    p.add_argument("--rerun-all", action="store_true",
                   help="Re-run all entries even if completed")
    args = p.parse_args()

    # Set environment variables for routing through the local LiteLLM proxy
    os.environ["OPENAI_API_KEY"] = args.api_key
    os.environ["OPENAI_BASE_URL"] = args.base_url

    results_save_path = os.path.join(args.results_dir, args.model, args.environment)
    os.makedirs(results_save_path, exist_ok=True)

    # Generate an isolated config file per run to avoid cross-run races.
    config_data = generate_config(
        environment=args.environment,
        model=args.model,
        entries=args.entries,
        max_turns=args.max_turns,
        results_save_path=results_save_path,
    )
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        prefix="benchforce_config_",
        dir=os.getcwd(),
        delete=False,
    ) as tmp_config:
        yaml.dump(config_data, tmp_config, default_flow_style=False)
        config_path = tmp_config.name

    os.environ["BENCHFORCE_CONFIG_PATH"] = config_path

    print(f"[benchforce] Running environment={args.environment} model={args.model} "
          f"mode=text entries={args.entries}")

    # Import and run benchforce
    from run import run
    from src.classes import parser
    from src.classes import runner
    from src.environments import configs

    config = parser.parse()

    # Determine entry numbers
    if args.entries == [-1]:
        env = configs[config.environment]
        entry_nums = [i + 1 for i in range(len(env["entries"]))]
    else:
        entry_nums = args.entries

    runner_id = runner.new_runner_id()
    print(f"[benchforce] runner_id={runner_id} entries={entry_nums}")

    try:
        run(
            runner_id=runner_id,
            entry_nums=entry_nums,
            skip_results=False,
            skip_upload=True,
            rerun_all=args.rerun_all,
            mode="text",
            agent_type="openai",
            config=config,
            run_iter=1,
        )
    finally:
        try:
            os.remove(config_path)
        except FileNotFoundError:
            pass

    print(f"[benchforce] Done. Results saved to {results_save_path}")


if __name__ == "__main__":
    main()
