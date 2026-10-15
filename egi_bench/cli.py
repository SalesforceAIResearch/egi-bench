"""Command line helpers for EGI-Bench."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = "results_aggregated"
BENCHMARK_NAMES = [
    "crmarena",
    "herb",
    "personabench",
    "userbench",
    "mcpuniverse",
    "mcpeval",
    "benchforce",
    "locobench",
]

FULL_COVERAGE_ENV = {
    "SERP_API_KEY": "SerpAPI key for MCP-Universe web_search domain",
    "GOOGLE_MAPS_API_KEY": "Google Maps API key for MCP-Universe location_navigation domain",
    "NPS_API_KEY": "NPS API key for MCPEval national_parks domain",
}

# Provider credentials the local LiteLLM proxy can route through. At
# least one must be set for the proxy to actually serve completions —
# which one(s) depend on the user's litellm_proxy/litellm_config.yaml
# routing. The doctor reports each one's state and only flags MISSING
# when *none* of them are set, since picking any one provider is a
# valid setup.
PROVIDER_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "VERTEX_PROJECT",
    "AWS_ACCESS_KEY_ID",
)


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""
    required: bool = True

    @property
    def status(self) -> str:
        if self.ok:
            return "OK"
        return "MISSING" if self.required else "SKIP"


def _load_env_no_overwrite(env_path: Path = REPO_ROOT / ".env") -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    placeholders = ("your-", "xxxxxxxx", "<", ">", "placeholder")
    return any(token in lowered for token in placeholders)


def _run_script(script: str, extra_env: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.call(["bash", str(REPO_ROOT / script)], cwd=REPO_ROOT, env=env)


def _latest_report(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    reports = [
        path
        for path in output_dir.glob("*.json")
        if path.is_file() and path.name != "latest.json"
    ]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)


def _print_checks(checks: Iterable[Check]) -> bool:
    failed_required = False
    for check in checks:
        marker = f"[{check.status}]"
        print(f"{marker:<10} {check.label}")
        if check.detail and not check.ok:
            print(f"           {check.detail}")
        if check.required and not check.ok:
            failed_required = True
    return not failed_required


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _load_run_all_module():
    module_name = "egi_bench._run_all"
    if module_name in sys.modules:
        return sys.modules[module_name]

    run_all_path = REPO_ROOT / "run_all.py"
    if not run_all_path.exists():
        raise SystemExit(f"Cannot find unified runner at {run_all_path}")

    spec = importlib.util.spec_from_file_location(module_name, run_all_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot import unified runner from {run_all_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def cmd_doctor(args: argparse.Namespace) -> int:
    _load_env_no_overwrite()
    checks: list[Check] = []

    checks.append(Check("Python 3.12+", sys.version_info >= (3, 12), sys.version.split()[0]))
    checks.append(Check("uv installed", _command_exists("uv"), "Install from https://github.com/astral-sh/uv"))
    checks.append(Check("root .env present", (REPO_ROOT / ".env").exists(), "Copy .env.example to .env"))
    checks.append(Check("benchmark_config.yaml present", (REPO_ROOT / "benchmark_config.yaml").exists()))

    # Accept any one provider credential as enough — the proxy's routing
    # decides which is required. We still surface each one's state for
    # visibility so the user knows what's wired up.
    provider_states = {
        name: not _is_placeholder(os.environ.get(name)) for name in PROVIDER_KEY_ENV_VARS
    }
    set_keys = [name for name, ok in provider_states.items() if ok]
    if set_keys:
        checks.append(
            Check(
                "provider credential set",
                True,
                f"set in .env: {', '.join(set_keys)} (litellm_proxy routes via litellm_config.yaml)",
            )
        )
    else:
        checks.append(
            Check(
                "provider credential set",
                False,
                "set at least one in .env so litellm_proxy can route LLM calls: "
                + ", ".join(PROVIDER_KEY_ENV_VARS),
            )
        )

    if args.mode == "deep":
        checks.append(Check("node available for MCP-Universe playwright", _command_exists("node"), required=True))
        checks.append(Check("npx available for MCP-Universe playwright", _command_exists("npx"), required=True))
        checks.append(Check("docker available for MCP-Universe postgres/WebArena", _command_exists("docker"), required=True))
        for key, description in FULL_COVERAGE_ENV.items():
            value = os.environ.get(key)
            checks.append(
                Check(
                    f"{key} set",
                    not _is_placeholder(value),
                    description,
                    required=args.full_coverage,
                )
            )

    if args.check_venvs:
        for name in BENCHMARK_NAMES:
            venv = REPO_ROOT / _venv_for_benchmark(name)
            present = (venv / "bin" / "python").exists()
            detail = (
                str(venv)
                if present
                else f"run `egi-bench setup` (or `cd {venv.parent.name} && uv venv && uv pip install -r requirements.txt`)"
            )
            checks.append(Check(f"{name} venv present", present, detail))

    if not args.no_network:
        checks.append(_gateway_health_check(args.health_url))

    ok = _print_checks(checks)
    if ok:
        print("\nDoctor completed successfully.")
        return 0
    print("\nDoctor found missing required setup.")
    return 1


def _gateway_health_check(health_url: str) -> Check:
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            return Check("litellm proxy health", response.status == 200, health_url)
    except (urllib.error.URLError, TimeoutError) as exc:
        # `egi-bench run` auto-spawns the proxy on demand, so a missing
        # proxy is not a hard error for most workflows. We surface it as
        # a non-required check ("not running, will auto-start on `run`")
        # plus point at `egi-bench proxy start` for users who want to
        # spin one up explicitly.
        return Check(
            "litellm proxy health",
            False,
            f"{health_url} ({exc}); not running. "
            "`egi-bench run` auto-spawns it, or start now with `egi-bench proxy start`.",
            required=False,
        )


def _venv_for_benchmark(name: str) -> Path:
    mapping = {
        "crmarena": Path("CRMArena/.venv"),
        "herb": Path("HERB/.venv"),
        "personabench": Path("PersonaBench/.venv"),
        "userbench": Path("UserBench/.venv"),
        "mcpuniverse": Path("MCP-Universe/.venv"),
        "mcpeval": Path("MCPEval/.venv"),
        "benchforce": Path("Benchforce/.venv"),
        "locobench": Path("LoCoBench/.venv"),
    }
    return mapping[name]


def cmd_setup(args: argparse.Namespace) -> int:
    if args.skip_data:
        print("Installing benchmark environments. Data setup is skipped.")
        return _run_script("scripts/install_all.sh", {"EGI_BENCH_SKIP_DATA": "1"})
    return _run_script("scripts/install_all.sh")


# ---------------------------------------------------------------------------
# `egi-bench proxy` subcommand
#
# Thin wrapper over the lifecycle helpers in run_all.py so users can
# explicitly manage the local LiteLLM proxy without touching the runner.
# Most users never need this — `egi-bench run` auto-spawns the proxy if
# nothing is up on :8008. Power users use `egi-bench proxy start` to
# share a single long-lived proxy across multiple back-to-back runs (so
# subsequent runs skip the ~5s startup), or `egi-bench proxy logs` to
# tail upstream provider errors.

def cmd_proxy(args: argparse.Namespace) -> int:
    _load_env_no_overwrite()
    run_all = _load_run_all_module()
    health_url = args.health_url or "http://localhost:8008/health/liveliness"

    action = args.proxy_action
    if action == "start":
        run_all.start_proxy(health_url)
        return 0
    if action == "stop":
        return 0 if run_all.stop_proxy() else 1
    if action == "status":
        info = run_all.proxy_status(health_url)
        kind_label = {
            "managed": "running (managed by egi-bench)",
            "managed-unhealthy": "started by egi-bench but NOT responding to /health",
            "external": "running (started outside egi-bench)",
            "stopped": "not running",
        }[info["kind"]]
        print(f"LiteLLM proxy: {kind_label}")
        if info["pid"] is not None:
            print(f"  pid:    {info['pid']}")
        print(f"  health: {info['health_url']} -> {'OK' if info['healthy'] else 'unreachable'}")
        return 0 if info["healthy"] else 1
    if action == "logs":
        log_file = run_all.PROXY_LOG_FILE
        if not log_file.exists():
            print(f"No proxy log at {log_file}. Has the proxy been started?")
            return 1
        if args.follow:
            os.execvp("tail", ["tail", "-n", str(args.lines), "-f", str(log_file)])
        os.execvp("tail", ["tail", "-n", str(args.lines), str(log_file)])
    print(f"Unknown proxy action: {action}", file=sys.stderr)
    return 2


def cmd_data(args: argparse.Namespace) -> int:
    return _run_script("scripts/download_data.sh")


def cmd_run(args: argparse.Namespace) -> int:
    run_all = _load_run_all_module()
    runner_args = ["--model", args.model, "--mode", args.mode]
    if args.benchmarks:
        runner_args.extend(["--benchmarks", *args.benchmarks])
    if args.parallel:
        runner_args.append("--parallel")
    if args.max_workers is not None:
        runner_args.extend(["--max-workers", str(args.max_workers)])
    if args.config != "benchmark_config.yaml":
        runner_args.extend(["--config", args.config])
    if args.output_dir != DEFAULT_OUTPUT_DIR:
        runner_args.extend(["--output-dir", args.output_dir])
    if args.egi_weights:
        runner_args.extend(["--egi-weights", args.egi_weights])
    if args.base_url:
        runner_args.extend(["--base-url", args.base_url])
    run_all.main(runner_args)
    return 0


def _rescore_runner_args(args: argparse.Namespace) -> list[str]:
    runner_args = ["--model", args.model, "--mode", args.mode, "--skip-run"]
    if args.benchmarks:
        runner_args.extend(["--benchmarks", *args.benchmarks])
    if args.config != "benchmark_config.yaml":
        runner_args.extend(["--config", args.config])
    if args.output_dir != DEFAULT_OUTPUT_DIR:
        runner_args.extend(["--output-dir", args.output_dir])
    if args.egi_weights:
        runner_args.extend(["--egi-weights", args.egi_weights])
    return runner_args


def cmd_report(args: argparse.Namespace) -> int:
    output_dir = REPO_ROOT / args.output_dir

    if args.rescore:
        if args.path:
            print("--rescore cannot be combined with --path", file=sys.stderr)
            return 2
        if not args.model or not args.mode:
            print("--rescore requires both --model and --mode", file=sys.stderr)
            return 2
        run_all = _load_run_all_module()
        runner_args = _rescore_runner_args(args)
        if args.json:
            with contextlib.redirect_stdout(io.StringIO()):
                run_all.main(runner_args)
            new_report = _latest_report(output_dir)
            if new_report is None:
                print(f"No aggregate report produced in {output_dir}", file=sys.stderr)
                return 1
            with new_report.open() as f:
                print(json.dumps(json.load(f), indent=2))
            return 0
        run_all.main(runner_args)
        return 0

    if args.model or args.mode or args.benchmarks or args.egi_weights:
        print(
            "--model/--mode/--benchmarks/--egi-weights only apply with --rescore",
            file=sys.stderr,
        )
        return 2

    report_path = Path(args.path) if args.path else _latest_report(output_dir)
    if report_path is None:
        print(f"No aggregate reports found in {output_dir}", file=sys.stderr)
        return 1
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    with report_path.open() as f:
        report = json.load(f)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    run_all = _load_run_all_module()
    print(f"Report: {report_path}")
    run_all.print_summary(report)
    logs_dir = output_dir / "logs"
    if logs_dir.exists():
        print(f"\nLogs: {logs_dir}")
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    targets = [REPO_ROOT / args.output_dir]
    if args.include_runtime:
        targets.append(REPO_ROOT / ".egi-bench")
    existing = [target for target in targets if target.exists()]
    if not existing:
        print("No generated EGI-Bench outputs found.")
        return 0
    print("Generated paths to remove:")
    for target in existing:
        print(f"  {target}")
    if not args.yes:
        answer = input("Remove these paths? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Clean cancelled.")
            return 0
    for target in existing:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    print("Generated outputs removed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="egi-bench",
        description="Set up, run, inspect, and clean EGI-Bench evaluations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check local setup and credentials")
    doctor.add_argument("--mode", choices=["quick", "deep"], default="quick")
    doctor.add_argument("--full-coverage", action="store_true", help="Require deep-mode opt-in credentials")
    # Venv presence is checked by default since a missing benchmark venv is the
    # most common failure mode for a fresh clone. Use --no-check-venvs to skip
    # when the CLI is being run before `egi-bench setup`.
    doctor.add_argument(
        "--check-venvs",
        dest="check_venvs",
        action="store_true",
        default=True,
        help="Verify per-benchmark virtual environments (default: on)",
    )
    doctor.add_argument(
        "--no-check-venvs",
        dest="check_venvs",
        action="store_false",
        help="Skip per-benchmark venv presence checks",
    )
    doctor.add_argument("--no-network", action="store_true", help="Skip litellm proxy health check")
    doctor.add_argument(
        "--health-url",
        default="http://localhost:8008/health/liveliness",
        help="Health endpoint of the local LiteLLM proxy.",
    )
    doctor.set_defaults(func=cmd_doctor)

    setup = subparsers.add_parser("setup", help="Install benchmark environments and data")
    setup.add_argument("--skip-data", action="store_true", help="Install dependencies without data setup")
    setup.set_defaults(func=cmd_setup)

    data = subparsers.add_parser("data", help="Download or preprocess benchmark data")
    data.set_defaults(func=cmd_data)

    run = subparsers.add_parser("run", help="Run benchmarks through the unified runner")
    run.add_argument("--model", required=True)
    run.add_argument("--mode", choices=["quick", "deep"], default="deep")
    run.add_argument("--benchmarks", nargs="+", choices=BENCHMARK_NAMES)
    run.add_argument("--parallel", action="store_true")
    run.add_argument("--max-workers", type=int)
    run.add_argument("--config", default="benchmark_config.yaml")
    run.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    run.add_argument(
        "--egi-weights",
        help=(
            "Per-invocation EGI Score weight overrides, e.g. M1=0.5,M5=0.2. "
            "Unspecified Ms keep their YAML default."
        ),
    )
    run.add_argument("--base-url")
    run.set_defaults(func=cmd_run)

    report = subparsers.add_parser(
        "report",
        help=(
            "Print an aggregate report. With --rescore, re-derive sub-scores "
            "from existing per-benchmark outputs and write a new aggregate."
        ),
    )
    report.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    report.add_argument("--path", help="Specific report JSON to print (without --rescore)")
    report.add_argument("--json", action="store_true", help="Print raw report JSON")
    report.add_argument(
        "--rescore",
        action="store_true",
        help=(
            "Re-score existing per-benchmark outputs and write a new aggregate "
            "report. Requires --model and --mode."
        ),
    )
    report.add_argument("--model", help="Model name (required with --rescore)")
    report.add_argument(
        "--mode",
        choices=["quick", "deep"],
        help="Execution profile to score (required with --rescore)",
    )
    report.add_argument(
        "--benchmarks",
        nargs="+",
        choices=BENCHMARK_NAMES,
        help="Subset of benchmarks to re-score (with --rescore). Defaults to all.",
    )
    report.add_argument("--config", default="benchmark_config.yaml")
    report.add_argument(
        "--egi-weights",
        help=(
            "EGI Score weight overrides for re-aggregation (with --rescore), "
            "e.g. M1=0.5,M5=0.2. Unspecified Ms keep their YAML default."
        ),
    )
    report.set_defaults(func=cmd_report)

    clean = subparsers.add_parser("clean", help="Remove generated aggregate outputs")
    clean.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    clean.add_argument("--include-runtime", action="store_true", help="Also remove .egi-bench runtime state")
    clean.add_argument("-y", "--yes", action="store_true", help="Do not prompt for confirmation")
    clean.set_defaults(func=cmd_clean)

    proxy = subparsers.add_parser(
        "proxy",
        help=(
            "Manage the local LiteLLM proxy. `egi-bench run` auto-spawns "
            "this for you, so most users never need these subcommands; "
            "use them when you want a single long-lived proxy across "
            "multiple runs, or to inspect upstream errors."
        ),
    )
    proxy.add_argument(
        "--health-url",
        default=None,
        help="Override the health endpoint (default http://localhost:8008/health/liveliness).",
    )
    proxy_actions = proxy.add_subparsers(dest="proxy_action", required=True)

    proxy_start = proxy_actions.add_parser(
        "start",
        help="Spawn the proxy in the background; idempotent if already running.",
    )
    proxy_start.set_defaults(func=cmd_proxy)

    proxy_stop = proxy_actions.add_parser(
        "stop",
        help="Stop a proxy previously started by egi-bench (no-op for external proxies).",
    )
    proxy_stop.set_defaults(func=cmd_proxy)

    proxy_status_p = proxy_actions.add_parser(
        "status",
        help="Print proxy state (managed / external / stopped) and health-check result.",
    )
    proxy_status_p.set_defaults(func=cmd_proxy)

    proxy_logs = proxy_actions.add_parser(
        "logs",
        help="Tail the proxy log (.egi-bench/proxy/proxy.log).",
    )
    proxy_logs.add_argument("-n", "--lines", type=int, default=50, help="Lines from the end (default 50).")
    proxy_logs.add_argument("-f", "--follow", action="store_true", help="Follow new lines (tail -f).")
    proxy_logs.set_defaults(func=cmd_proxy)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
