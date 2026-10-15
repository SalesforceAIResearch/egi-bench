"""Run a native MCP-Universe domain via BenchmarkRunner.

Spawns the runner with an LLM config patched to the local LiteLLM proxy (port 8008, gpt-4.1
by default) regardless of what the upstream YAML specifies. Dumps a
BenchmarkReport and prints a per-task pass/fail JSON summary to stdout (also
saved under `results_aggregated/mcpu_native/` by default; override with
--output-dir, which is what `run_all.py` passes).

Accepts either a `*_test` stem (upstream's 2-3 task smoke) or a plain domain
stem (`financial_analysis`) whose full task list can be capped via --max-tasks.

Usage (from repo root):
  MCP-Universe/.venv/bin/python scripts/run_mcpuniverse.py financial_analysis --max-tasks 20
  MCP-Universe/.venv/bin/python scripts/run_mcpuniverse.py web_search_test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent.parent.resolve()
MCPU_ROOT = REPO_ROOT / "MCP-Universe"

# Make the canonical reasoning-model helper at the repo root importable from
# under MCP-Universe's venv. The helper is pure stdlib (``re``-only), so it
# loads fine in any Python 3.10+ environment without bringing extra deps.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from egi_bench.reasoning_models import (  # noqa: E402
    DEFAULT_REASONING_MAX_TOKENS,
    is_long_context_reasoning_model,
)

# Surface one concise line per outbound HTTP request in the per-benchmark log,
# matching the other EGI-Bench wrappers. Keep httpcore quiet so connection-pool
# internals do not drown out task output.
_httpx_logger = logging.getLogger("httpx")
_httpx_logger.setLevel(logging.INFO)
if not _httpx_logger.handlers:
    _httpx_handler = logging.StreamHandler(sys.stderr)
    _httpx_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    _httpx_logger.addHandler(_httpx_handler)
_httpx_logger.propagate = False
logging.getLogger("httpcore").setLevel(logging.WARNING)

load_dotenv(MCPU_ROOT / ".env")

_venv_bin = MCPU_ROOT / ".venv" / "bin"
if _venv_bin.exists():
    os.environ["PATH"] = f"{_venv_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    os.environ["VIRTUAL_ENV"] = str(MCPU_ROOT / ".venv")

sys.path.insert(0, str(MCPU_ROOT))

from mcpuniverse.benchmark.runner import BenchmarkRunner  # noqa: E402
from mcpuniverse.benchmark.report import BenchmarkReport  # noqa: E402
from mcpuniverse.tracer.collectors import FileCollector  # noqa: E402


GATEWAY_BASE_URL = os.environ.get("MCPU_GATEWAY_URL", "http://localhost:8008/v1")
GATEWAY_MODEL = os.environ.get("MCPU_GATEWAY_MODEL", "gpt-4.1")


def build_patched_config(
    original_yaml: Path,
    max_tasks: int | None,
    seed: int,
    unique_suffix: str,
) -> Path:
    """Patch the LLM block to the gateway, optionally sample tasks, write a sibling YAML.

    Parallel runs use different ``unique_suffix`` values so the patched files
    do not collide on disk.
    """
    with open(original_yaml) as f:
        docs = list(yaml.safe_load_all(f))

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind", "").lower()
        if kind == "llm":
            # Force the LLM type to openai so the local LiteLLM proxy
            # (OpenAI-compatible) is used regardless of what the upstream YAML
            # specified (some configs use `openrouter`, `anthropic`, etc.
            # which take different kwargs).
            spec = doc.setdefault("spec", {})
            spec["type"] = "openai"
            cfg = spec.setdefault("config", {})
            cfg["model_name"] = GATEWAY_MODEL
            cfg["base_url"] = GATEWAY_BASE_URL
            cfg["api_key"] = "unused"
            # Strip provider-specific knobs that openai doesn't accept.
            for stale in ("reasoning", "reasoning_effort", "provider"):
                cfg.pop(stale, None)
            if "temperature" not in cfg:
                cfg["temperature"] = 0.0
            # Reasoning models (Gemini 2.5 / 3, Claude 3.7 + 4.x, OpenAI
            # o-series + gpt-5*, deepseek-r1) burn most of their per-call
            # output budget on internal thinking tokens. Override any
            # upstream cap (the bundled YAMLs default to ~4096) with a
            # reasoning-sized cap so the agent's ReAct loop has room for
            # both the thought trace and the visible tool call.
            if is_long_context_reasoning_model(GATEWAY_MODEL):
                cfg["max_completion_tokens"] = max(
                    cfg.get("max_completion_tokens") or 0,
                    DEFAULT_REASONING_MAX_TOKENS,
                )
            elif "max_completion_tokens" not in cfg:
                cfg["max_completion_tokens"] = 4096
        elif kind == "agent":
            # Some upstream configs use `harmony_react` (which relies on
            # openrouter-style `reasoning`) or other provider-specific agent
            # variants. Since we force the LLM to vanilla openai (via the
            # local LiteLLM proxy), downgrade the agent to plain `react` so
            # it doesn't try to read
            # attributes that openai doesn't expose.
            agent_spec = doc.setdefault("spec", {})
            if agent_spec.get("type") in {"harmony_react"}:
                agent_spec["type"] = "react"
        elif kind == "benchmark" and max_tasks is not None:
            spec = doc.setdefault("spec", {})
            tasks = spec.get("tasks", [])
            if len(tasks) > max_tasks:
                rng = random.Random(seed)
                spec["tasks"] = sorted(rng.sample(tasks, max_tasks))

    patched = original_yaml.with_name(
        f"{original_yaml.stem}_patched_{unique_suffix}.yaml"
    )
    with open(patched, "w") as f:
        yaml.dump_all(docs, f, default_flow_style=False, allow_unicode=True)
    return patched


# Patterns that indicate a tool call hit an upstream rate limit / quota error.
# `web_search` triggers 429s on serpapi.com, `location_navigation` can trigger
# them on maps.googleapis.com or via the OpenAI-compatible RateLimitError; we
# also catch generic quota-exceeded language so future domains (e.g. notion)
# light up automatically. Patterns are case-insensitive.
_RATE_LIMIT_PATTERNS = re.compile(
    r"HTTP/1\.\d\s+429"          # any HTTP 429 response
    r"|429\s+Too\s+Many\s+Requests"
    r"|RateLimitError"            # OpenAI/openai-python exception class name
    r"|quota.{0,20}exceed"        # "quota exceeded" / "quota has been exceeded"
    r"|rate.?limit.{0,30}exceed",
    re.IGNORECASE,
)


def scan_rate_limits(log_path: Path, task_trace_ids: Dict[str, str]) -> Dict[str, int]:
    """Count rate-limit signals attributed to each task via trace-id matching.

    The FileCollector log is a stream of JSON span objects separated by
    ``------`` divider lines. Every span carries a ``trace_id`` that
    BenchmarkRunner allocates per-task (returned in
    ``BenchmarkResult.task_trace_ids``). We invert the task→trace mapping and
    count regex matches inside each span belonging to a known task.

    Counting matches across the whole span blob (rather than per-line) means
    a single upstream 429 response that gets duplicated across nested fields
    (text/result/response.content[0].text) inflates the hit count slightly —
    that's acceptable: the binary "task was affected" classification is what
    drives partial-result scoring; the count only flows into transparency
    fields in the summary JSON.

    Returns ``{task_name: hit_count}`` with one entry per task in
    ``task_trace_ids`` (zero when clean).
    """
    counts: Dict[str, int] = {name: 0 for name in task_trace_ids}
    if not log_path.exists() or not task_trace_ids:
        return counts
    trace_to_task = {tid: task for task, tid in task_trace_ids.items() if tid}
    if not trace_to_task:
        return counts

    def _flush(blob: str) -> None:
        if not blob.strip():
            return
        try:
            span = json.loads(blob)
        except json.JSONDecodeError:
            return
        if not isinstance(span, dict):
            return
        task = trace_to_task.get(span.get("trace_id"))
        if not task:
            return
        hits = len(_RATE_LIMIT_PATTERNS.findall(blob))
        if hits:
            counts[task] += hits

    try:
        with open(log_path, "r", errors="replace") as fh:
            buf: List[str] = []
            for line in fh:
                if line.startswith("---"):
                    _flush("".join(buf))
                    buf = []
                else:
                    buf.append(line)
            _flush("".join(buf))
    except OSError:
        pass
    return counts


def _sweep_stale_patched(configs_dir: Path) -> None:
    """Remove leftover `*_patched_*.yaml` files from earlier crashes.

    The patched YAML is unlink()ed in the normal ``finally`` path, but killed
    or hard-crashed runs leave the file on disk. Sweeping at startup keeps the
    configs dir clean and avoids confusing BenchmarkRunner with dead files.
    """
    for stale in configs_dir.glob("*_patched_*.yaml"):
        try:
            stale.unlink()
        except OSError:
            pass


async def run_benchmark(
    stem: str,
    max_tasks: int | None,
    seed: int,
    output_dir: Path | None = None,
) -> dict:
    configs_dir = MCPU_ROOT / "mcpuniverse" / "benchmark" / "configs" / "mcpuniverse"
    _sweep_stale_patched(configs_dir)
    original = configs_dir / f"{stem}.yaml"
    if not original.exists():
        raise SystemExit(f"Missing config: {original}")

    unique_suffix = uuid.uuid4().hex[:8]
    patched = build_patched_config(original, max_tasks, seed, unique_suffix)

    log_dir = MCPU_ROOT / "log" / "mcpuniverse"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{stem}_{unique_suffix}.log"

    runner_path = f"mcpuniverse/{patched.name}"

    trace_collector = FileCollector(log_file=str(log_file))
    start = time.time()
    try:
        benchmark = BenchmarkRunner(runner_path)
        results = await benchmark.run(trace_collector=trace_collector)
    finally:
        try:
            patched.unlink()
        except FileNotFoundError:
            pass
    elapsed = time.time() - start

    summary: dict = {
        "config": stem,
        "model": GATEWAY_MODEL,
        "wall_clock_seconds": round(elapsed, 2),
        "max_tasks": max_tasks,
        "seed": seed,
        "tasks": [],
    }
    total_passed = 0
    total_evals = 0
    tasks_fully_passed = 0
    task_trace_ids: Dict[str, str] = {}
    for run_result in results:
        # Collect the BenchmarkRunner's task→trace_id map so we can attribute
        # rate-limit signals in the FileCollector log back to specific tasks.
        task_trace_ids.update(getattr(run_result, "task_trace_ids", {}) or {})
        for task_name, task_result in run_result.task_results.items():
            evals = task_result.get("evaluation_results", [])
            passed = sum(1 for e in evals if getattr(e, "passed", False))
            total = len(evals)
            all_passed = passed == total and total > 0
            if all_passed:
                tasks_fully_passed += 1
            total_passed += passed
            total_evals += total
            summary["tasks"].append(
                {
                    "task": task_name,
                    "evaluations_passed": passed,
                    "evaluations_total": total,
                    "all_passed": all_passed,
                }
            )

    # Per-task rate-limit attribution. Tasks that hit upstream 429s / quota
    # errors during execution are tagged so score_mcpuniverse in run_all.py
    # can recompute pass-rates from the clean subset and surface a
    # ``partial_reason`` (which flips the aggregate into ``degraded`` state
    # without losing the model-quality signal from unaffected tasks).
    rl_hits = scan_rate_limits(log_file, task_trace_ids)
    rl_passed_clean = 0
    rl_total_clean = 0
    rl_tasks_affected = 0
    rl_total_hits = 0
    for entry in summary["tasks"]:
        hits = rl_hits.get(entry["task"], 0)
        entry["rate_limit_hits"] = hits
        rl_total_hits += hits
        if hits > 0:
            rl_tasks_affected += 1
        else:
            rl_passed_clean += entry["evaluations_passed"]
            rl_total_clean += entry["evaluations_total"]

    summary["aggregate"] = {
        "tasks_total": len(summary["tasks"]),
        "tasks_fully_passed": tasks_fully_passed,
        "sub_evaluations_passed": total_passed,
        "sub_evaluations_total": total_evals,
        "task_pass_rate": round(
            tasks_fully_passed / len(summary["tasks"]) * 100, 2
        ) if summary["tasks"] else 0.0,
        "sub_eval_pass_rate": round(
            total_passed / total_evals * 100, 2
        ) if total_evals else 0.0,
        # Pass rate over only tasks that did NOT hit a rate-limit response.
        # Equal to ``sub_eval_pass_rate`` when no tasks were affected, lower-N
        # when some were dropped. ``None`` if every task was rate-limited
        # (no clean signal to report).
        "sub_eval_pass_rate_clean": round(
            rl_passed_clean / rl_total_clean * 100, 2
        ) if rl_total_clean else None,
    }
    summary["rate_limit"] = {
        "tasks_total": len(summary["tasks"]),
        "tasks_affected": rl_tasks_affected,
        "total_hits": rl_total_hits,
        "log_file": str(log_file),
    }

    try:
        BenchmarkReport(benchmark, trace_collector=trace_collector).dump()
    except Exception as exc:  # noqa: BLE001
        summary["report_dump_error"] = str(exc)

    out_dir = output_dir if output_dir is not None else REPO_ROOT / "results_aggregated" / "mcpu_native"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # ``GATEWAY_MODEL`` may be a provider-prefixed identifier (``vertex/...``,
    # ``bedrock/...``, ``together_ai/...``) or include colons. Naively
    # interpolating it into the filename would produce a phantom subdirectory
    # like ``<stem>_vertex/gemini-2.5-flash_<ts>.json`` whose parent is never
    # created, so the JSON dump (and therefore ``score_mcpuniverse``'s read)
    # silently fail at the end of every domain run.
    safe_model = GATEWAY_MODEL.replace("/", "_").replace(":", "_")
    out_path = out_dir / f"{stem}_{safe_model}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    summary["saved_to"] = str(out_path)
    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("stem", help="YAML stem under configs/mcpuniverse/ (e.g. financial_analysis)")
    parser.add_argument("--max-tasks", type=int, default=None, help="Cap tasks via random sample (default: run all)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for task sampling")
    parser.add_argument("--output-dir", default=None, help="Override directory for summary JSON")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    output_dir = Path(args.output_dir) if args.output_dir else None
    summary = asyncio.run(run_benchmark(args.stem, args.max_tasks, args.seed, output_dir))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
