#!/usr/bin/env python3
"""
Wrapper to run LoCoBench evaluation via the LiteLLM proxy.

Sets up environment for the LiteLLM proxy (OpenAI-compatible endpoint at 0.0.0.0:8008)
and delegates to the locobench CLI evaluate command.

Usage:
    # Run with defaults (gpt-5-nano, easy difficulty, 5 scenarios)
    uv run python run_eval_litellm.py

    # Custom model and difficulty
    uv run python run_eval_litellm.py --model gpt-5-nano --difficulty medium

    # Specific task category
    uv run python run_eval_litellm.py --model gpt-5-nano --task-category bug_investigation

    # Full evaluation (all scenarios, all difficulties)
    uv run python run_eval_litellm.py --model gpt-5-nano --full

    # Quick evaluation (50 sampled easy scenarios)
    uv run python run_eval_litellm.py --model gpt-5-nano --num-scenarios 50
"""
import os
import sys
import subprocess
import argparse

# Configure for LiteLLM proxy (OpenAI-compatible endpoint)
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["OPENAI_BASE_URL"] = os.getenv("OPENAI_BASE_URL", "http://0.0.0.0:8008/v1")
# Prevent local traffic from being routed via corporate/system proxies.
os.environ["NO_PROXY"] = os.getenv("NO_PROXY", "localhost,127.0.0.1,0.0.0.0")
os.environ["no_proxy"] = os.environ["NO_PROXY"]


def _sample_scenarios(script_dir, num_scenarios, difficulty, seed):
    """Create a temp scenarios dir with sampled files; return temp dir path or None."""
    import json
    import random
    import shutil
    import tempfile
    from pathlib import Path

    scenarios_dir = Path(script_dir) / "data" / "output" / "scenarios"
    if not scenarios_dir.exists():
        return None

    all_files = list(scenarios_dir.glob("*.json"))
    if difficulty:
        filtered = []
        for f in all_files:
            try:
                with open(f) as fp:
                    d = json.load(fp)
                if d.get("difficulty") == difficulty:
                    filtered.append(f)
            except Exception:
                pass
        all_files = filtered
    if not all_files:
        return None

    random.seed(seed)
    sampled = random.sample(all_files, min(num_scenarios, len(all_files)))

    tmp_dir = Path(tempfile.mkdtemp(prefix="locobench_sample_"))
    for f in sampled:
        shutil.copy2(f, tmp_dir / f.name)
    return str(tmp_dir)


def main():
    parser = argparse.ArgumentParser(description="Run LoCoBench evaluation via the LiteLLM proxy")
    parser.add_argument("--model", "-m", default="gpt-5-nano",
                        help="Model to evaluate (default: gpt-5-nano)")
    parser.add_argument("--difficulty", "-d", choices=["easy", "medium", "hard", "expert"],
                        default=None, help="Difficulty level (default: all)")
    parser.add_argument("--task-category", "-t", default=None,
                        help="Task category to evaluate (default: all)")
    parser.add_argument("--output-file", "-o", default=None,
                        help="Output file for results")
    parser.add_argument("--full", action="store_true",
                        help="Run full evaluation (all difficulties, all categories)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Start fresh (ignore existing checkpoints)")
    parser.add_argument("--max-concurrent-scenarios", type=int, default=3,
                        help="Max concurrent scenarios (default: 3)")
    parser.add_argument("--num-scenarios", type=int, default=None,
                        help="Limit to N randomly sampled scenarios (default: all)")
    parser.add_argument("--scenario-seed", type=int, default=42,
                        help="Random seed for scenario sampling (default: 42)")

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    effective_difficulty = args.difficulty or (None if args.full else "easy")
    tmp_scenarios_dir = None

    # If num-scenarios is set, create a temp dir with sampled scenarios and patch config
    patched_config = None
    if args.num_scenarios is not None:
        import shutil
        import tempfile
        import yaml
        from pathlib import Path

        tmp_scenarios_dir = _sample_scenarios(
            script_dir, args.num_scenarios, effective_difficulty, args.scenario_seed
        )
        if tmp_scenarios_dir:
            # Write a patched config.yaml pointing to the temp scenarios dir
            config_path = Path(script_dir) / "config.yaml"
            with open(config_path) as f:
                config_data = yaml.safe_load(f)
            # Patch the scenarios output dir
            if "data" in config_data and "output_dir" in config_data["data"]:
                orig_output = config_data["data"]["output_dir"]
                # Point scenarios subdir to our temp dir's parent (the evaluator appends /scenarios)
                config_data["data"]["output_dir"] = str(Path(tmp_scenarios_dir).parent)
                # But evaluator appends /scenarios, so we need tmp_scenarios_dir to be named "scenarios"
                import os as _os
                scenarios_name = _os.path.basename(tmp_scenarios_dir)
                if scenarios_name != "scenarios":
                    new_parent = str(Path(tmp_scenarios_dir).parent / "locobench_sampled")
                    _os.makedirs(new_parent, exist_ok=True)
                    target = str(Path(new_parent) / "scenarios")
                    shutil.move(tmp_scenarios_dir, target)
                    tmp_scenarios_dir = target
                    config_data["data"]["output_dir"] = new_parent

            tmp_cfg = tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False, dir=script_dir
            )
            yaml.dump(config_data, tmp_cfg, default_flow_style=False)
            tmp_cfg.close()
            patched_config = tmp_cfg.name
            print(f"[run_eval_litellm] Sampling {args.num_scenarios} scenarios → {tmp_scenarios_dir}")

    # Build locobench evaluate command
    config_arg = patched_config or "config.yaml"
    cmd = [
        sys.executable, "-m", "locobench.cli",
        "evaluate",
        "--config-path", config_arg,
        "--model", args.model,
        "--max-concurrent-scenarios", str(args.max_concurrent_scenarios),
    ]

    if args.difficulty:
        cmd.extend(["--difficulty", args.difficulty])
    elif not args.full:
        # Default to easy for quick testing
        cmd.extend(["--difficulty", "easy"])

    if args.task_category:
        cmd.extend(["--task-category", args.task_category])

    if args.output_file:
        cmd.extend(["--output-file", args.output_file])

    if args.no_resume:
        cmd.append("--no-resume")

    print("=" * 60)
    print("LoCoBench Evaluation via LiteLLM proxy")
    print("=" * 60)
    print(f"Gateway:    {os.environ['OPENAI_BASE_URL']}")
    print(f"Model:      {args.model}")
    print(f"Difficulty: {effective_difficulty or 'all'}")
    print(f"Category:   {args.task_category or 'all'}")
    if args.num_scenarios:
        print(f"Scenarios:  {args.num_scenarios} (sampled, seed={args.scenario_seed})")
    print(f"Command:    {' '.join(cmd)}")
    print("=" * 60)
    print()

    try:
        result = subprocess.run(cmd, cwd=script_dir, env=os.environ.copy())
    finally:
        if patched_config and os.path.exists(patched_config):
            os.unlink(patched_config)
        if tmp_scenarios_dir and os.path.exists(os.path.dirname(tmp_scenarios_dir)):
            import shutil
            shutil.rmtree(os.path.dirname(tmp_scenarios_dir), ignore_errors=True)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
