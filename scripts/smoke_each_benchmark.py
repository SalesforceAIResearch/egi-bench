#!/usr/bin/env python3
"""Run each EGI-Bench benchmark with a per-benchmark timeout.

This is intentionally a smoke-test helper: each benchmark gets a short
window to start, reach the model, and surface obvious setup errors. A timeout
is treated as expected smoke-test completion, then the next benchmark runs.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


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


@dataclass
class SmokeResult:
    benchmark: str
    status: str
    elapsed_seconds: float
    returncode: int | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runner_python(root: Path) -> Path:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def terminate_process_group(process: subprocess.Popen[object], grace_seconds: float) -> None:
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def run_one(
    *,
    benchmark: str,
    model: str,
    mode: str,
    timeout_seconds: int,
    kill_grace_seconds: float,
    extra_args: list[str],
) -> SmokeResult:
    root = repo_root()
    command = [
        str(runner_python(root)),
        str(root / "run_all.py"),
        "--model",
        model,
        "--mode",
        mode,
        "--benchmarks",
        benchmark,
        *extra_args,
    ]

    print("\n" + "=" * 80, flush=True)
    print(f"[smoke] {benchmark}: starting, timeout={timeout_seconds}s", flush=True)
    print(f"[smoke] command: {' '.join(command)}", flush=True)

    started = time.monotonic()
    process = subprocess.Popen(command, cwd=root, start_new_session=True)
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        terminate_process_group(process, grace_seconds=kill_grace_seconds)
        elapsed = time.monotonic() - started
        print(f"[smoke] {benchmark}: timed out after {elapsed:.1f}s; killed", flush=True)
        return SmokeResult(benchmark, "timeout", elapsed)

    elapsed = time.monotonic() - started
    if returncode == 0:
        status = "passed"
    else:
        status = "failed"
    print(
        f"[smoke] {benchmark}: {status} after {elapsed:.1f}s "
        f"(exit={returncode})",
        flush=True,
    )
    return SmokeResult(benchmark, status, elapsed, returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run EGI-Bench benchmarks sequentially with a fixed timeout per "
            "benchmark. Timed-out benchmarks are killed and the script "
            "continues to the next benchmark."
        )
    )
    parser.add_argument("--model", required=True, help="Model route to smoke test.")
    parser.add_argument(
        "--mode",
        default="quick",
        choices=["quick", "deep"],
        help="Benchmark profile to run. Defaults to quick.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Seconds to allow each benchmark before killing it. Defaults to 180.",
    )
    parser.add_argument(
        "--kill-grace-seconds",
        type=float,
        default=10.0,
        help="Seconds to wait after SIGTERM before SIGKILL. Defaults to 10.",
    )
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        choices=BENCHMARK_NAMES,
        default=BENCHMARK_NAMES,
        help="Optional subset of benchmarks. Defaults to all benchmarks.",
    )
    parser.add_argument(
        "extra_run_all_args",
        nargs=argparse.REMAINDER,
        help=(
            "Extra arguments passed to run_all.py after a '--' separator, "
            "for example: -- --base-url http://localhost:8008/v1"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    extra_args = args.extra_run_all_args
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]

    results = [
        run_one(
            benchmark=benchmark,
            model=args.model,
            mode=args.mode,
            timeout_seconds=args.timeout_seconds,
            kill_grace_seconds=args.kill_grace_seconds,
            extra_args=extra_args,
        )
        for benchmark in args.benchmarks
    ]

    print("\n" + "=" * 80, flush=True)
    print("[smoke] summary", flush=True)
    for result in results:
        exit_text = "" if result.returncode is None else f", exit={result.returncode}"
        print(
            f"[smoke] {result.benchmark:12s} {result.status:8s} "
            f"{result.elapsed_seconds:7.1f}s{exit_text}",
            flush=True,
        )

    failures = [result for result in results if result.status == "failed"]
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
