#!/usr/bin/env python3
"""EGI-Bench unified benchmark runner."""

import argparse
import atexit
import glob
import json
import os
import re
import shlex
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).parent.resolve()

# ``egi_bench/`` lives next to this file at the repo root. Make the canonical
# reasoning-model helper importable when ``python run_all.py`` is invoked
# directly (the cwd-on-sys.path heuristic does NOT cover the case where
# ``run_all.py`` is being driven from a different working directory by
# ``egi-bench run``).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from egi_bench.reasoning_models import (  # noqa: E402
    DEFAULT_REASONING_MAX_TOKENS,
    is_long_context_reasoning_model,
    is_openai_reasoning_model,
)

# Chain-loaded .env files. Order matters: the first file wins for any given
# key, so the root .env takes precedence over per-benchmark fallbacks. This
# lets users keep one master file while still reading keys that upstream
# benchmarks ship in their own .env. Per-benchmark keys (GOOGLE_MAPS_API_KEY,
# SERP_API_KEY, etc.) are then visible to gating checks in this runner, not
# just to the subprocess.
_ENV_FILES = [
    REPO_ROOT / ".env",
    REPO_ROOT / "MCP-Universe" / ".env",
]


def _load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'")
            # Never overwrite shell-exported values or earlier files in the
            # chain; this preserves "first-file wins" and user shell overrides.
            if key and val and key not in os.environ:
                os.environ[key] = val


def _load_env_chain() -> None:
    for env_file in _ENV_FILES:
        _load_env_file(env_file)


_load_env_chain()


# ---------------------------------------------------------------------------
# Shared constants and result model
# ---------------------------------------------------------------------------

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

TASK_ACRONYMS = {
    "case_routing": "NCR",
    "handle_time": "HTU",
    "transfer_count": "TCU",
    "named_entity_disambiguation": "NED",
    "policy_violation_identification": "PVI",
    "knowledge_qa": "KQA",
    "top_issue_identification": "TII",
    "best_region_identification": "BRI",
    "monthly_trend_analysis": "MTA",
}

@dataclass
class BenchmarkResult:
    name: str
    score: float
    sub_scores: Dict[str, float] = field(default_factory=dict)
    raw_metrics: Dict = field(default_factory=dict)
    status: str = "pending"
    error_message: Optional[str] = None
    # ``None`` means the runtime is unknown (e.g. when re-scoring without a fresh
    # run). A numeric value is the wall-clock time of the most recent run.
    runtime_seconds: Optional[float] = None
    # Free-form human-readable notes (e.g. "skipped <cat>: missing <env vars>")
    # that should surface in the aggregated report without triggering the
    # `degraded` soft-fail state. Used by benchmarks with opt-in sub-tasks.
    notes: List[str] = field(default_factory=list)
    # When set, the benchmark contributed a numeric score but from a partial
    # run (e.g. checkpoint fallback after a timeout kill). The string is a
    # short human-readable explanation that is appended to ``degraded_reasons``
    # and triggers the ``DEGRADED`` soft-fail state, while the score still
    # counts toward the overall aggregate.
    partial_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

class ProgressTracker:
    PHASE_ICON = {"waiting": ".", "running": ">>", "scoring": "~~", "done": "OK", "error": "!!"}

    def __init__(self, bench_names: list, interval: float = 10.0):
        self._lock = threading.Lock()
        self._benchmarks = {n: {"phase": "waiting", "detail": "", "start": None} for n in bench_names}
        self._order = list(bench_names)
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()

    def update(self, name: str, phase: str, detail: str = ""):
        with self._lock:
            entry = self._benchmarks[name]
            entry["phase"] = phase
            entry["detail"] = detail
            if phase == "running" and entry["start"] is None:
                entry["start"] = time.time()
        self._print_status()

    def _elapsed(self, entry) -> str:
        if entry["start"] is None:
            return ""
        secs = int(time.time() - entry["start"])
        mins, secs = divmod(secs, 60)
        return f"{mins}m{secs:02d}s" if mins else f"{secs}s"

    def _format_line(self) -> str:
        parts = []
        with self._lock:
            for name in self._order:
                e = self._benchmarks[name]
                token = f"{name}[{self.PHASE_ICON.get(e['phase'], '?')}]"
                elapsed = self._elapsed(e)
                if elapsed:
                    token += f" {elapsed}"
                if e["detail"]:
                    token += f" {e['detail']}"
                parts.append(token)
        return "  |  ".join(parts)

    def _print_status(self):
        print(f"[progress] {self._format_line()}", flush=True)

    def _refresh_loop(self):
        while not self._stop_event.wait(self._interval):
            with self._lock:
                active = any(e["phase"] in ("running", "scoring") for e in self._benchmarks.values())
            if active:
                self._print_status()

    def finish(self):
        self._stop_event.set()
        self._thread.join(timeout=2)
        self._print_status()


# ---------------------------------------------------------------------------
# Configuration and environment helpers
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        venv_python = REPO_ROOT / ".venv" / "bin" / "python"
        if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
            os.execv(str(venv_python), [str(venv_python), *sys.argv])
        raise SystemExit(
            "Missing runner dependency: PyYAML is required to read "
            f"{path}.\nRun `./scripts/install_all.sh`, then use "
            "`.venv/bin/python run_all.py ...`, or install it in the current "
            "environment with `python -m pip install -r requirements.txt`."
        ) from exc

    with open(path) as f:
        return yaml.safe_load(f) or {}


def mode_profile(bench: dict, mode: str) -> dict:
    modes = bench.get("modes")
    if not isinstance(modes, dict) or mode not in modes:
        bench_label = bench.get("dir", "<unknown benchmark>")
        raise KeyError(f"Missing modes.{mode} profile for {bench_label}")
    return modes[mode] or {}


def mode_items(bench: dict, mode: str, key: str) -> list:
    profile = mode_profile(bench, mode)
    if key not in profile:
        bench_label = bench.get("dir", "<unknown benchmark>")
        raise KeyError(f"Missing modes.{mode}.{key} for {bench_label}")
    return profile[key]


# Per-subprocess wall-clock cap (in seconds) sourced from
# ``defaults.subprocess_timeout_seconds.<mode>`` in benchmark_config.yaml.
# Falls back to 12h if the YAML is missing the block (e.g. older configs)
# so we never inherit the historical 2h default that caused silent SIGKILLs
# mid-run on slow local environments.
_DEFAULT_SUBPROCESS_TIMEOUT_FALLBACK = 43200  # 12h


def default_subprocess_timeout(config: dict, mode: str) -> int:
    """Return the global subprocess timeout (seconds) for ``mode``.

    Individual benchmarks may further override via
    ``modes.<mode>.timeout_seconds`` -- but they should always default to
    *this* value rather than the legacy ``run_in_venv`` default, so a slow
    environment cannot silently re-introduce mid-run kills.
    """

    timeouts = config.get("defaults", {}).get("subprocess_timeout_seconds", {})
    if mode in timeouts:
        try:
            return int(timeouts[mode])
        except (TypeError, ValueError):
            pass
    return _DEFAULT_SUBPROCESS_TIMEOUT_FALLBACK


def discover_userbench_envs(data_root: Optional[str] = None) -> List[str]:
    root = data_root or os.environ.get("TRAVELGYM_DATA_PATH", str(REPO_ROOT / "UserBench" / "data"))
    if not os.path.isdir(root):
        raise ValueError(
            f"UserBench deep mode requested all envs, but data root does not exist: {root}"
        )
    envs = sorted(
        name[: -len("_multiturn")]
        for name in os.listdir(root)
        if name.endswith("_multiturn")
        and os.path.isdir(os.path.join(root, name))
        and not name.endswith("_multiturn_onechoice")
    )
    if not envs:
        raise ValueError(
            f"UserBench deep mode requested all envs, but found none under: {root}"
        )
    return envs


# ---------------------------------------------------------------------------
# LiteLLM proxy checks
# ---------------------------------------------------------------------------

def check_gateway_health(health_url: str):
    try:
        resp = urllib.request.urlopen(health_url, timeout=5)
        if resp.status != 200:
            print(f"[run_all] WARNING: litellm proxy returned status {resp.status}")
            sys.exit(1)
        print("[run_all] LiteLLM proxy is healthy.")
    except Exception as e:
        print(f"[run_all] ERROR: cannot reach litellm proxy at {health_url}: {e}")
        print("  Start it with: cd litellm_proxy && bash start_server.sh")
        sys.exit(1)


# Substrings that signal "the proxy is up but the upstream credential
# (OpenAI/Anthropic/Gemini/SFR/...) is missing or invalid". LiteLLM's
# error envelope nests upstream errors under "AuthenticationError" and
# usually mentions "api_key" in the body, so checking for either is
# enough to diagnose missing-key situations across providers without
# hard-coding provider names. Keep substrings lowercase; we lowercase
# the body before matching.
_LITELLM_AUTH_ERROR_MARKERS = (
    "authenticationerror",
    "incorrect api key",
    "invalid api key",
    "missing api key",
    "no api key",
    "api_key is required",
)


def check_gateway_inference_ready(base_url: str, model: str):
    """Fail fast when proxy is up but cannot serve completions.

    Keep the payload minimal: no ``temperature`` / ``top_p`` /
    ``max_tokens`` because:

    * OpenAI reasoning models (gpt-5*/o-series) reject any non-default
      ``temperature``/``top_p`` with HTTP 400 ("Only the default (1)
      value is supported"), which would surface here as a spurious
      "proxy is broken" failure even though the route is configured
      correctly. (The proxy's per-route ``additional_drop_params``
      handles the same problem for downstream benchmark calls.)
    * Reasoning models burn output tokens on hidden thinking, so a
      tight ``max_tokens=1`` cap returns "max_tokens or model output
      limit was reached" before any visible reply is generated, again
      surfacing as a false-negative readiness failure.

    The probe only needs a 200 OK to confirm auth + routing; response
    length and determinism don't matter, so omit those knobs entirely.
    The 60s timeout accommodates reasoning-model first-token latency.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                body = resp.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"LiteLLM proxy inference check failed ({resp.status}): {body}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        body_lower = body.lower()
        if any(marker in body_lower for marker in _LITELLM_AUTH_ERROR_MARKERS):
            print(
                "[run_all] ERROR: litellm proxy is running but the upstream API key for "
                f"model {model!r} is missing or invalid."
            )
            print(
                "  Fix: set the relevant provider key (OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                "GEMINI_API_KEY, VERTEX_PROJECT, AWS_ACCESS_KEY_ID, ...) in the repo-root .env,"
            )
            print(
                "  then restart `cd litellm_proxy && bash start_server.sh`. "
                "See litellm_proxy/litellm_config.yaml for the per-model routing."
            )
            sys.exit(1)
        if "model not found" in body_lower or "not a valid model" in body_lower:
            print(
                f"[run_all] ERROR: model {model!r} is not declared in "
                "litellm_proxy/litellm_config.yaml."
            )
            print(
                "  Fix: add a model_list entry for it (see litellm_proxy/README.md), "
                "then restart the proxy."
            )
            sys.exit(1)
        print(f"[run_all] ERROR: litellm proxy inference check failed ({e.code}): {body}")
        sys.exit(1)
    except Exception as e:
        print(f"[run_all] ERROR: litellm proxy inference readiness check failed: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# LiteLLM proxy lifecycle (auto-spawn / status / stop)
# ---------------------------------------------------------------------------
#
# State files live under .egi-bench/proxy/ at the repo root:
#   - proxy.pid       PID of the spawned `litellm` process (when we own it).
#   - proxy.log       stdout+stderr from the spawned process.
#
# Ownership: a proxy started by `egi-bench run` is "owned" by that run and
# torn down on exit. A proxy started by `egi-bench proxy start` (or by a
# manual `bash start_server.sh`) is "external" and outlives the run. Both
# cases speak the same OpenAI surface on http://localhost:8008/v1, so the
# benchmarks don't care which one is up.

PROXY_STATE_DIR = REPO_ROOT / ".egi-bench" / "proxy"
PROXY_PID_FILE = PROXY_STATE_DIR / "proxy.pid"
PROXY_LOG_FILE = PROXY_STATE_DIR / "proxy.log"
PROXY_DIR = REPO_ROOT / "litellm_proxy"
PROXY_BIN = PROXY_DIR / ".venv" / "bin" / "litellm"
PROXY_PYTHON = PROXY_DIR / ".venv" / "bin" / "python"
PROXY_CONFIG = PROXY_DIR / "litellm_config.yaml"


def _proxy_is_responsive(health_url: str, timeout: float = 1.5) -> bool:
    """Return True iff health_url returns 200 within `timeout` seconds."""
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _read_proxy_pid() -> Optional[int]:
    """Return the PID we last spawned, or None if the file is gone or stale."""
    if not PROXY_PID_FILE.exists():
        return None
    try:
        pid = int(PROXY_PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    # os.kill(pid, 0) is the standard "is this process alive" probe on POSIX.
    try:
        os.kill(pid, 0)
    except OSError:
        # Stale pidfile (process gone). Clean up so the next start doesn't
        # mistake it for a live proxy.
        try:
            PROXY_PID_FILE.unlink()
        except OSError:
            pass
        return None
    return pid


def proxy_status(health_url: str) -> dict:
    """Return a small status dict for `egi-bench proxy status` and doctor."""
    pid = _read_proxy_pid()
    healthy = _proxy_is_responsive(health_url)
    if pid is not None and healthy:
        kind = "managed"            # we spawned it and it answers /health
    elif pid is not None and not healthy:
        kind = "managed-unhealthy"  # we spawned it but it doesn't answer
    elif pid is None and healthy:
        kind = "external"           # someone else (likely `bash start_server.sh`) is running it
    else:
        kind = "stopped"
    return {"kind": kind, "pid": pid, "health_url": health_url, "healthy": healthy}


def _wait_for_health(health_url: str, timeout_s: float = 30.0, poll_s: float = 0.5) -> bool:
    """Block until health_url returns 200, or `timeout_s` elapses."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _proxy_is_responsive(health_url, timeout=1.0):
            return True
        time.sleep(poll_s)
    return False


def _port_from_health_url(health_url: str) -> int:
    """Extract the proxy port from health_url; default to 8008."""
    try:
        return urllib.parse.urlsplit(health_url).port or 8008
    except Exception:
        return 8008


def start_proxy(health_url: str, wait_timeout_s: float = 30.0) -> int:
    """Spawn the LiteLLM proxy and return its PID. No-op if already healthy.

    Raises SystemExit on missing venv or startup timeout. The returned PID
    is also written to PROXY_PID_FILE so a later `stop_proxy()` (or another
    egi-bench process) can find and kill it.
    """
    PROXY_STATE_DIR.mkdir(parents=True, exist_ok=True)

    if _proxy_is_responsive(health_url):
        # Something is already listening on 8008 and answering /health.
        # Don't spawn a duplicate.
        existing_pid = _read_proxy_pid()
        if existing_pid is not None:
            print(f"[run_all] LiteLLM proxy already running (managed, pid={existing_pid}).")
        else:
            print("[run_all] LiteLLM proxy already running (external, not managed by egi-bench).")
        return existing_pid or -1

    if not PROXY_BIN.exists():
        print(
            "[run_all] ERROR: litellm proxy venv not found at "
            f"{PROXY_BIN.relative_to(REPO_ROOT)}."
        )
        print("  Fix: run `egi-bench setup` (or `cd litellm_proxy && uv venv && uv pip install -r requirements.txt`).")
        sys.exit(1)

    port = _port_from_health_url(health_url)
    log_fp = open(PROXY_LOG_FILE, "ab")
    log_fp.write(
        f"\n[egi-bench {datetime.now().isoformat()}] starting litellm proxy on port {port}\n".encode()
    )
    log_fp.flush()

    proc = subprocess.Popen(
        [str(PROXY_BIN), "--config", str(PROXY_CONFIG), "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(PROXY_DIR),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        # Detach into a new process group so a Ctrl-C in the parent doesn't
        # kill the proxy mid-shutdown — we want explicit, ordered teardown
        # via stop_proxy() instead.
        start_new_session=True,
    )
    PROXY_PID_FILE.write_text(str(proc.pid))

    print(
        f"[run_all] Spawned litellm proxy (pid={proc.pid}); "
        f"waiting up to {int(wait_timeout_s)}s for /health/liveliness ..."
    )
    if not _wait_for_health(health_url, timeout_s=wait_timeout_s):
        # Surface the tail of the proxy log so the user sees the actual
        # failure (e.g. config parse error, port conflict) instead of an
        # opaque timeout.
        try:
            tail = PROXY_LOG_FILE.read_text(errors="ignore").splitlines()[-25:]
        except OSError:
            tail = []
        print(f"[run_all] ERROR: litellm proxy failed to come up on {health_url} within {int(wait_timeout_s)}s.")
        if tail:
            print(f"[run_all] Last lines of {PROXY_LOG_FILE.relative_to(REPO_ROOT)}:")
            for line in tail:
                print(f"  {line}")
        # Best-effort cleanup; the process may have died on its own.
        stop_proxy(quiet=True)
        sys.exit(1)
    print("[run_all] LiteLLM proxy is healthy.")
    return proc.pid


def stop_proxy(quiet: bool = False) -> bool:
    """Stop the proxy we previously spawned. Returns True if a process was killed."""
    pid = _read_proxy_pid()
    if pid is None:
        if not quiet:
            print("[run_all] No managed litellm proxy is running.")
        return False
    try:
        # SIGTERM gives uvicorn a clean shutdown; uvicorn handles it within
        # a couple of seconds for our config (no streaming clients to drain).
        os.kill(pid, 15)
        # Brief wait so we don't return before the port is released.
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            # Still alive after 2s — escalate.
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    except OSError as e:
        if not quiet:
            print(f"[run_all] WARNING: failed to stop litellm proxy pid={pid}: {e}")
    finally:
        try:
            PROXY_PID_FILE.unlink()
        except OSError:
            pass
    if not quiet:
        print(f"[run_all] Stopped litellm proxy (pid={pid}).")
    return True


# ---------------------------------------------------------------------------
# Subprocess execution
# ---------------------------------------------------------------------------

def run_in_venv(
    benchmark_dir: str,
    venv_path: str,
    cmd: str,
    env_overrides: Optional[Dict] = None,
    timeout: int = _DEFAULT_SUBPROCESS_TIMEOUT_FALLBACK,
    log_file: Optional[str] = None,
    label: str = "",
    tracker: Optional["ProgressTracker"] = None,
) -> subprocess.CompletedProcess:
    python_bin = os.path.join(venv_path, "bin", "python")
    full_cmd = cmd.replace("python ", f"{python_bin} ", 1)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["VIRTUAL_ENV"] = venv_path
    env["PATH"] = os.path.join(venv_path, "bin") + ":" + env.get("PATH", "")
    if env_overrides:
        env.update(env_overrides)

    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as lf:
            lf.write(f"$ {full_cmd}\n$ cwd: {benchmark_dir}\n\n")

    proc = subprocess.Popen(
        full_cmd,
        shell=True,
        cwd=benchmark_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    stdout_lines = []
    deadline = time.time() + timeout

    def _reader():
        for line in proc.stdout:
            stdout_lines.append(line)
            if log_file:
                with open(log_file, "a") as lf:
                    lf.write(line)
            if tracker and ("error" in line.lower() or "failed" in line.lower()):
                tracker.update(label, "running", f"ERR: {line.strip()[:50]}")

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()
    reader_thread.join(timeout=max(1, deadline - time.time()))
    if proc.poll() is None:
        proc.kill()
        reader_thread.join(timeout=5)
    proc.wait()
    return subprocess.CompletedProcess(args=full_cmd, returncode=proc.returncode, stdout="".join(stdout_lines), stderr="")


# ---------------------------------------------------------------------------
# CRMArena
# ---------------------------------------------------------------------------

def run_crmarena(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["crmarena"]
    profile = mode_profile(bench, mode)
    tasks = mode_items(bench, mode, "tasks")
    defaults = bench["default_args"]
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    result_dir = f"results/unified/{model}"
    timeout_seconds = default_subprocess_timeout(config, mode)

    # The agent loop honors --base_url explicitly, but the CRMArena Evaluator
    # (`crm_sandbox/env/env.py:Evaluator.parse_answers` /
    # `compute_privacy_confidential_awareness_score`) calls litellm.completion(
    # model="gpt-4o-2024-08-06", custom_llm_provider="openai") which reads the
    # endpoint from OPENAI_BASE_URL / OPENAI_API_KEY at request time. Without
    # these overrides the evaluator leaks to api.openai.com directly with the
    # parent shell's key, bypassing the LiteLLM proxy and the judge-pin
    # rationale. Routing it through the proxy keeps the judge stack pinned to
    # the same OpenAI direct route as HERB / MCP-Universe / UserBench /
    # BenchForce, which is what makes EGI scores apple-to-apple across runs.
    env_overrides = {"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url}

    for i, task in enumerate(tasks):
        if tracker:
            tracker.update("crmarena", "running", f"task {i + 1}/{len(tasks)}: {task}")
        cmd = (
            f"python -u run_tasks.py --model {model} --task_category {task} "
            f"--agent_eval_mode {defaults['agent_eval_mode']} --log_dir {result_dir} "
            f"--agent_strategy {defaults['agent_strategy']} --llm_provider {defaults['llm_provider']} "
            f"--org_type {defaults['org_type']} --base_url {base_url} --reuse_results "
            f"--max_tasks_per_category {profile.get('max_tasks_per_category', 0)} "
            f"--sample_seed {profile.get('sample_seed', 42)}"
        )
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="crmarena",
            tracker=tracker,
        )


def score_crmarena(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench_dir = REPO_ROOT / config["benchmarks"]["crmarena"]["dir"]
    result_dir = bench_dir / f"results/unified/{model}"
    task_results = defaultdict(list)
    for f in glob.glob(str(result_dir / "results_*.json")):
        with open(f) as fh:
            for r in json.load(fh):
                task_results[r["task_type"]].append(r)
    if not task_results:
        return BenchmarkResult(name="crmarena", score=0, status="error", error_message=f"No results in {result_dir}")

    sub_scores = {}
    for task_type, results in task_results.items():
        rewards = []
        for r in results:
            reward = r["reward"]
            if isinstance(reward, (int, float)):
                rewards.append(float(reward))
            elif isinstance(reward, dict):
                # Prefer F1 when present. Open-ended KQA tasks ship with both
                # `em` (exact-match — 0 for every answer that isn't byte-equal
                # to the reference) and `f1`/`bleu`/`rouge`. Checking `em`
                # first used to collapse KQA to 0.0 even when the model
                # produced semantically correct answers.
                if "f1" in reward:
                    rewards.append(float(reward["f1"]))
                elif "em" in reward:
                    rewards.append(1.0 if reward["em"] else 0.0)
        acc = (sum(rewards) / len(rewards)) if rewards else 0.0
        sub_scores[TASK_ACRONYMS.get(task_type, task_type.upper())] = round(acc * 100, 2)
    overall = round(sum(sub_scores.values()) / len(sub_scores), 2) if sub_scores else 0.0
    return BenchmarkResult(name="crmarena", score=overall, sub_scores=sub_scores, raw_metrics=dict(sub_scores), status="success")


# ---------------------------------------------------------------------------
# HERB
# ---------------------------------------------------------------------------

def run_herb(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["herb"]
    profile = mode_profile(bench, mode)
    modes = mode_items(bench, mode, "modes")
    defaults = bench["default_args"]
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    max_questions = profile.get("max_questions")
    embedding_mode = profile.get("embedding_mode", defaults["embedding_mode"])
    embedding_model_name = profile.get("embedding_model_name", defaults["embedding_model_name"])
    # ``context_window`` is required by HERB's ``OpenAILike`` LLM (used so the
    # adapter can serve any OpenAI-wire-compatible model name through the
    # gateway, including those not in llama-index's hardcoded registry such as
    # ``gpt-5.5``). Default to 400k tokens (the gpt-5 / 5.1 / 5.2 base window;
    # the gpt-5-chat-latest / gpt-4o variant is 128k, gpt-5.5 / gpt-4.1 is ~1M).
    # Operators can override per-mode in ``benchmark_config.yaml``.
    context_window = int(profile.get("context_window", defaults.get("context_window", 400000)))
    timeout_seconds = default_subprocess_timeout(config, mode)
    # Only pass --reuse_index if a previously-built index actually exists.
    index_path = REPO_ROOT / bench["dir"] / "index" / embedding_model_name / "all" / "docstore.json"
    reuse_flag = " --reuse_index" if index_path.exists() else ""
    for i, run_mode in enumerate(modes):
        if tracker:
            tracker.update("herb", "running", f"mode {i + 1}/{len(modes)}: {run_mode}")
        cmd = (
            f"python rag.py --mode {run_mode} --model_name {model} --api_base {base_url} "
            f"--embedding_mode {embedding_mode} --embedding_model_name {embedding_model_name} "
            f"--max_workers {defaults['max_workers']} --num_attempts {defaults['num_attempts']} "
            f"--context_window {context_window}{reuse_flag}"
        )
        # After the first iteration the index will exist, so subsequent modes can reuse it.
        reuse_flag = " --reuse_index"
        if max_questions is not None:
            cmd += f" --max_questions {int(max_questions)}"
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides={"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url},
            log_file=log_file,
            label="herb",
            tracker=tracker,
        )
    if tracker:
        tracker.update("herb", "running", "judging")
    # Only evaluate output files for the current model to avoid re-judging old runs
    model_safe = model.replace("/", "_").replace(":", "_")
    for pk_file in glob.glob(str((REPO_ROOT / bench["dir"] / "output") / f"*{model_safe}*.pk")):
        run_in_venv(
            bench_dir,
            venv_dir,
            f"python evaluate.py --output_file {pk_file}",
            timeout=timeout_seconds,
            env_overrides={"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url},
            log_file=log_file,
            label="herb",
            tracker=tracker,
        )


def score_herb(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench = config["benchmarks"]["herb"]
    output_dir = REPO_ROOT / bench["dir"] / "output"
    venv_python = str(REPO_ROOT / bench["venv"] / "bin" / "python")
    if not output_dir.exists():
        return BenchmarkResult(name="herb", score=0, status="error", error_message=f"No output dir: {output_dir}")
    model_safe = model.replace("/", "_").replace(":", "_")
    pk_files = [p for p in list(output_dir.glob("*.pk")) + list(output_dir.glob("*.pkl")) if model_safe in p.name]
    if not pk_files:
        return BenchmarkResult(name="herb", score=0, status="error", error_message="No pickle result files found")

    # Use HERB venv to load pickle files (which depend on llama_index).
    # Answerable runs store {"gpt4-correctness": [...], "type": [...]} per question.
    # Unanswerable runs store {"unanswerable_results": [{"q","a","s"}, ...]} where
    # s == 1 means the model correctly refused to answer (the question is unanswerable).
    score_script = """
import pickle, json, sys
from collections import defaultdict
from pathlib import Path

pk_files = [Path(p) for p in sys.argv[1:]]
sub_scores = {}
for pk_file in pk_files:
    try:
        with open(pk_file, "rb") as f:
            dataset = pickle.load(f)
    except Exception:
        continue
    unans = dataset.get("unanswerable_results")
    if unans:
        flags = [item.get("s") for item in unans if isinstance(item, dict) and item.get("s") is not None]
        if flags:
            avg = sum(flags) / len(flags)
            sub_scores[pk_file.stem + "_unanswerable"] = round(avg * 100, 2)
        continue
    correctness = dataset.get("gpt4-correctness", [])
    types = dataset.get("type", [])
    type_scores = defaultdict(list)
    for i, qtype in enumerate(types):
        if i < len(correctness) and correctness[i] is not None:
            type_scores[qtype].append(correctness[i])
    for qtype, scores in type_scores.items():
        avg = sum(scores) / len(scores)
        sub_scores[pk_file.stem + "_" + qtype] = round(avg * 100 if qtype != "content" else avg, 2)
print(json.dumps(sub_scores))
"""
    result = subprocess.run(
        [venv_python, "-c", score_script] + [str(p) for p in pk_files],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        return BenchmarkResult(name="herb", score=0, status="error", error_message=f"HERB scoring failed: {result.stderr[:200]}")
    try:
        sub_scores = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return BenchmarkResult(name="herb", score=0, status="error", error_message="HERB scoring JSON parse failed")

    if not sub_scores:
        return BenchmarkResult(name="herb", score=0, status="error", error_message="No scored results")

    # Detect silent unanswerable failures: a *-unans.pk pickle exists on disk
    # (so `--mode unans` was run) but produced no `_unanswerable` sub-score.
    # This happens when ``evaluate.py`` failed to load the pickle (e.g. the
    # llama-index ``AttributedDict`` deserialization bug) and never wrote
    # ``unanswerable_results`` back. Without this check the aggregate report
    # looks complete (M5 just silently loses the herb contributor).
    unans_pickles_present = any("unans" in p.stem.lower() for p in pk_files)
    has_unans_score = any(k.endswith("_unanswerable") for k in sub_scores)
    partial_reason = None
    if unans_pickles_present and not has_unans_score:
        missing_stems = sorted(
            p.stem for p in pk_files if "unans" in p.stem.lower()
        )
        partial_reason = (
            "unanswerable evaluation missing for "
            + ", ".join(missing_stems)
            + " (likely evaluate.py pickle load failure; rerun evaluate.py on the *-unans.pk file)"
        )

    overall = round(sum(sub_scores.values()) / len(sub_scores), 2)
    return BenchmarkResult(
        name="herb",
        score=overall,
        sub_scores=sub_scores,
        raw_metrics=dict(sub_scores),
        status="success",
        partial_reason=partial_reason,
    )


# ---------------------------------------------------------------------------
# PersonaBench
# ---------------------------------------------------------------------------

def _check_correctness(prediction, answer):
    pred = str(prediction).lower().strip()
    if isinstance(answer, list):
        return any(str(a).lower().strip() in pred or pred in str(a).lower().strip() for a in answer)
    ans = str(answer).lower().strip()
    return ans in pred or pred in ans


def run_personabench(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["personabench"]
    defaults = bench["default_args"].copy()
    defaults.update(mode_profile(bench, mode).get("args", {}))
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    communities = defaults["test_community_ids"].split(",")
    timeout_seconds = default_subprocess_timeout(config, mode)
    for i, community in enumerate(communities):
        if tracker:
            tracker.update("personabench", "running", f"community {i + 1}/{len(communities)}: {community}")
        cmd = (
            f"python run_eval_litellm.py --data_dir {defaults['data_dir']} --base_models {model} "
            f"--retrievers {defaults['retrievers']} --test_community_ids {community} "
            f"--test_noises {defaults['test_noises']} --num_people {defaults['num_people']} "
            f"--num_chunks {defaults['num_chunks']}"
        )
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            log_file=log_file,
            label="personabench",
            tracker=tracker,
        )


def score_personabench(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench = config["benchmarks"]["personabench"]
    defaults = bench["default_args"].copy()
    defaults.update(mode_profile(bench, mode).get("args", {}))
    bench_dir = REPO_ROOT / bench["dir"]
    dataset_name = defaults["data_dir"].split("/")[-1]
    num_chunks = defaults["num_chunks"]
    results_dir = bench_dir / "logs" / dataset_name / f"results_all_community_chunk_{num_chunks}"
    noise_files = sorted(glob.glob(str(results_dir / "result_noise_*.json")))
    if not noise_files:
        return BenchmarkResult(name="personabench", score=0, status="error", error_message=f"No results in {results_dir}")
    sub_scores = {}
    all_accuracies = []
    for nf in noise_files:
        with open(nf) as fh:
            data = json.load(fh)
        for model_result in data:
            if model not in model_result["Model"]:
                continue
            results = model_result["Results"]
            correct = 0
            by_type = defaultdict(lambda: {"correct": 0, "total": 0})
            for r in results:
                is_correct = _check_correctness(r["prediction"], r["answer"])
                if is_correct:
                    correct += 1
                q_type = r["type"]
                by_type[q_type]["total"] += 1
                if is_correct:
                    by_type[q_type]["correct"] += 1
            all_accuracies.append((correct / len(results)) * 100 if results else 0)
            for q_type, stats in by_type.items():
                type_key = q_type.replace(" ", "_")
                sub_scores[f"{Path(nf).stem}_{type_key}"] = round((stats["correct"] / stats["total"] * 100) if stats["total"] else 0, 2)
    if not all_accuracies:
        return BenchmarkResult(name="personabench", score=0, status="error", error_message="No matching results")
    overall = round(sum(all_accuracies) / len(all_accuracies), 2)
    return BenchmarkResult(name="personabench", score=overall, sub_scores=sub_scores, raw_metrics=dict(sub_scores), status="success")


# ---------------------------------------------------------------------------
# UserBench
# ---------------------------------------------------------------------------

def _userbench_save_name(model: str, mode: str) -> str:
    # Scope cached results/reward_cache by mode so a quick-mode run with a
    # ``max_tasks_per_env`` cap doesn't poison a subsequent deep-mode run that
    # expects the full task set. ``UserBench/eval.py`` skips per-env when the
    # results file already has a pass_k entry for that env, so sharing one
    # ``unified_<model>.json`` across modes silently re-uses the smaller
    # quick-mode rollouts.
    #
    # Also sanitize ``/`` and ``:`` out of the model identifier: UserBench's
    # ``eval.py`` interpolates ``--save_name`` straight into
    # ``outputs/results_<save_name>.json`` and ``outputs/reward_cache_<save_name>.json``
    # without creating intermediate directories. A raw provider-prefixed name
    # like ``vertex/gemini-2.5-flash`` would otherwise be interpreted as a
    # subdirectory and crash every write with ``FileNotFoundError``.
    safe_model = model.replace("/", "_").replace(":", "_")
    return f"unified_{safe_model}_{mode}"


def run_userbench(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["userbench"]
    envs = mode_items(bench, mode, "envs")
    if "__all__" in envs:
        envs = discover_userbench_envs()
    profile = mode_profile(bench, mode)
    max_tasks_per_env = profile.get("max_tasks_per_env")
    defaults = bench["default_args"]
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    port = base_url.rstrip("/").split(":")[-1].split("/")[0]
    env_overrides = {"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url}
    save_name = _userbench_save_name(model, mode)
    timeout_seconds = default_subprocess_timeout(config, mode)
    # OpenAI reasoning models (gpt-5*/o-series) reject any non-default
    # `temperature` with HTTP 400 ("Only the default (1) value is
    # supported"). Omit the `--temperature` flag for those models so
    # UserBench's eval.py falls back to its own default of 1.0, which
    # matches what the upstream actually runs at. Also keeps the
    # logged invocation honest -- we don't claim to have requested a
    # temperature that was never honored. Non-reasoning models (and
    # non-OpenAI reasoning models like Gemini 2.5+/Claude 3.7+) keep
    # the configured temperature for run-to-run reproducibility.
    omit_temperature = is_openai_reasoning_model(model)
    temperature_flag = "" if omit_temperature else f"--temperature {defaults['temperature']} "
    for i, env_name in enumerate(envs):
        if tracker:
            tracker.update("userbench", "running", f"env {i + 1}/{len(envs)}: {env_name}")
        cmd = (
            f"python eval.py --model_name {model} --port {port} --max_turns {defaults['max_turns']} "
            f"--pass_k {defaults['pass_k']} {temperature_flag}--envs {env_name} --save_name {save_name}"
        )
        if max_tasks_per_env is not None:
            cmd += f" --max_tasks_per_env {max_tasks_per_env}"
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="userbench",
            tracker=tracker,
        )


def score_userbench(config: dict, model: str, mode: str) -> BenchmarkResult:
    outputs_dir = REPO_ROOT / config["benchmarks"]["userbench"]["dir"] / "outputs"
    save_name = _userbench_save_name(model, mode)
    results_file = outputs_dir / f"results_{save_name}.json"
    # Backwards compatibility: older runs wrote ``results_unified_<model>.json``
    # without the mode suffix. Fall back to that path so previously-collected
    # results can still be rescored without re-running the benchmark.
    if not results_file.exists():
        legacy_file = outputs_dir / f"results_unified_{model}.json"
        if legacy_file.exists():
            results_file = legacy_file
    if not results_file.exists():
        return BenchmarkResult(name="userbench", score=0, status="error", error_message="No UserBench results found")
    with open(results_file) as f:
        results = json.load(f)
    sub_scores = {}
    values = []
    for env_name, passes in results.items():
        pass_data = passes.get("1", passes.get(1, {}))
        micro_avg = pass_data.get("micro_avg", 0)
        sub_scores[f"{env_name}_micro_avg"] = round(micro_avg * 100, 2)
        values.append(micro_avg * 100)
    overall = round(sum(values) / len(values), 2) if values else 0.0
    return BenchmarkResult(name="userbench", score=overall, sub_scores=sub_scores, raw_metrics=dict(sub_scores), status="success")


# ---------------------------------------------------------------------------
# MCP-Universe (native domains)
#
# The runner invokes `scripts/run_mcpuniverse.py` once per domain. That script
# patches the upstream YAML's LLM block to the local LiteLLM proxy
# (OpenAI-compatible) and optionally caps the task list, then drives
# MCP-Universe's BenchmarkRunner. Each invocation writes a summary JSON into
# the per-model results dir under MCP-Universe. score_mcpuniverse reads those
# summaries back.
# ---------------------------------------------------------------------------

def _skipped_optional_domains(bench: dict, domains: List[str]) -> Dict[str, List[str]]:
    """Return {domain: missing_env_vars} for opt-in domains whose creds are unset.

    Generic helper shared by any benchmark whose YAML defines an
    ``optional_domains`` mapping (currently mcpuniverse and mcpeval). Each
    entry maps a domain name to a list of required env vars; if any are
    unset in the current process env, the domain is reported as skipped so
    the caller can drop it from the run/score path with a note rather than
    failing the whole benchmark.
    """
    optional = bench.get("optional_domains") or {}
    skipped: Dict[str, List[str]] = {}
    for domain in domains:
        required = optional.get(domain)
        if not required:
            continue
        missing = [v for v in required if not os.environ.get(v)]
        if missing:
            skipped[domain] = missing
    return skipped


def _mcpu_summary_dir(model: str, mode: str) -> Path:
    return REPO_ROOT / "MCP-Universe" / "results" / "unified" / f"{model}_{mode}"


def run_mcpuniverse(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["mcpuniverse"]
    profile = mode_profile(bench, mode)
    domains = mode_items(bench, mode, "domains")
    skipped = _skipped_optional_domains(bench, domains)
    runnable = [d for d in domains if d not in skipped]

    if skipped and tracker:
        for domain, missing in skipped.items():
            tracker.update("mcpuniverse", "running", f"skip {domain}: missing {','.join(missing)}")
    if skipped and log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as lf:
            for domain, missing in skipped.items():
                lf.write(f"[mcpuniverse] skipping domain '{domain}': missing env vars {missing}\n")

    max_tasks = profile.get("max_tasks_per_domain")
    seed = profile.get("sample_seed", 42)
    summary_dir = _mcpu_summary_dir(model, mode)
    summary_dir.mkdir(parents=True, exist_ok=True)
    # Start clean so score_mcpuniverse only sees summaries from this run.
    for stale in summary_dir.glob("*.json"):
        stale.unlink()

    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    runner_script = str(REPO_ROOT / "scripts" / "run_mcpuniverse.py")

    # MCPU_GATEWAY_* drives the YAML patcher in scripts/run_mcpuniverse.py, which
    # rewrites each domain's `llm-1` block to point the agent's main loop at
    # the local LiteLLM proxy. That covers the agent's reasoning calls.
    #
    # OPENAI_BASE_URL / OPENAI_API_KEY are a second, distinct codepath. Some
    # MCP-Universe evaluators construct their own OpenAI client without honoring
    # the patched llm config (e.g. google_search.llm_as_a_judge at
    # mcpuniverse/evaluator/google_search/functions.py: `OpenAI(api_key=
    # context.get_env("OPENAI_API_KEY"))` with no base_url, plus the analogous
    # deepresearch.hle_llm_as_a_judge). Without these env vars the evaluator
    # leaks to api.openai.com and 401s, scoring every task 0 even when the
    # agent loop succeeds — observed as `web_search: 0.0` in deep runs.
    # Routing the evaluator through the same gateway keeps M2 valid.
    env_overrides = {
        "MCPU_GATEWAY_URL": base_url,
        "MCPU_GATEWAY_MODEL": model,
        "OPENAI_BASE_URL": base_url,
        "OPENAI_API_KEY": "dummy",
    }
    timeout_seconds = default_subprocess_timeout(config, mode)

    for i, domain in enumerate(runnable):
        if tracker:
            tracker.update("mcpuniverse", "running", f"domain {i + 1}/{len(runnable)}: {domain}")
        cmd = f"python -u {runner_script} {domain} --seed {seed} --output-dir {summary_dir}"
        if max_tasks is not None:
            cmd += f" --max-tasks {max_tasks}"
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="mcpuniverse",
            tracker=tracker,
        )


def score_mcpuniverse(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench = config["benchmarks"]["mcpuniverse"]
    domains = mode_items(bench, mode, "domains")
    skipped = _skipped_optional_domains(bench, domains)
    summary_dir = _mcpu_summary_dir(model, mode)

    sub_scores: Dict[str, float] = {}
    raw_metrics: Dict[str, dict] = {}
    notes: List[str] = []
    rate_limited_domains: List[str] = []
    for domain in domains:
        if domain in skipped:
            continue
        # Each run_mcpuniverse.py invocation writes one JSON per domain.
        matches = sorted(summary_dir.glob(f"{domain}_*.json"), key=lambda p: p.stat().st_mtime)
        if not matches:
            continue
        with open(matches[-1]) as f:
            summary = json.load(f)
        agg = summary.get("aggregate", {})
        rate_limit = summary.get("rate_limit", {})
        rl_affected = rate_limit.get("tasks_affected", 0)
        rl_total = rate_limit.get("tasks_total", agg.get("tasks_total", 0))
        rl_total_hits = rate_limit.get("total_hits", 0)

        # When a portion of tasks hit upstream rate limits (serpapi 429s for
        # web_search, maps quota errors for location_navigation, etc.), the
        # all-tasks ``sub_eval_pass_rate`` conflates env failure with model
        # quality. Score from the clean subset instead — that's the
        # "partial result" semantics. ``sub_eval_pass_rate_clean`` is None
        # only when *every* task was rate-limited; in that case we keep the
        # all-tasks rate (the score is 0.0 anyway) and let the
        # ``partial_reason`` flag the problem to the reader.
        clean_rate = agg.get("sub_eval_pass_rate_clean")
        full_rate = round(agg.get("sub_eval_pass_rate", 0.0), 2)
        if rl_affected and clean_rate is not None:
            sub_scores[domain] = round(clean_rate, 2)
            rate_limited_domains.append(domain)
            notes.append(
                f"{domain}: {rl_affected}/{rl_total} tasks hit upstream rate "
                f"limits ({rl_total_hits} HTTP 429/quota events); "
                f"score computed from {rl_total - rl_affected} clean tasks "
                f"(clean={clean_rate} all={full_rate})"
            )
        else:
            sub_scores[domain] = full_rate
            if rl_affected:
                # Every task was rate-limited; surface it but keep the (0)
                # score so the user sees the env exhaustion explicitly.
                rate_limited_domains.append(domain)
                notes.append(
                    f"{domain}: ALL {rl_total} tasks hit upstream rate "
                    f"limits ({rl_total_hits} HTTP 429/quota events); "
                    f"no clean tasks left to score"
                )

        raw_metrics[domain] = {
            "task_pass_rate": agg.get("task_pass_rate"),
            "sub_eval_pass_rate": agg.get("sub_eval_pass_rate"),
            "sub_eval_pass_rate_clean": clean_rate,
            "tasks_fully_passed": agg.get("tasks_fully_passed"),
            "tasks_total": agg.get("tasks_total"),
            "sub_evaluations_passed": agg.get("sub_evaluations_passed"),
            "sub_evaluations_total": agg.get("sub_evaluations_total"),
            "wall_clock_seconds": summary.get("wall_clock_seconds"),
            "rate_limit_tasks_affected": rl_affected,
            "rate_limit_total_hits": rl_total_hits,
        }

    notes.extend(
        f"skipped '{domain}' (opt-in): set {', '.join(missing)} to enable"
        for domain, missing in sorted(skipped.items())
    )

    if not sub_scores:
        if skipped and len(skipped) == len(domains):
            return BenchmarkResult(
                name="mcpuniverse",
                score=0,
                status="error",
                error_message=(
                    "All configured mcpuniverse domains were skipped for missing "
                    "credentials. Set the required env vars or trim "
                    "`optional_domains` in benchmark_config.yaml."
                ),
                notes=notes,
            )
        return BenchmarkResult(
            name="mcpuniverse",
            score=0,
            status="error",
            error_message=f"No MCP-Universe summaries in {summary_dir}",
            notes=notes,
        )

    overall = round(sum(sub_scores.values()) / len(sub_scores), 2)
    if skipped:
        raw_metrics["_skipped_domains"] = {d: sorted(m) for d, m in skipped.items()}

    # Trip ``partial_reason`` when any domain was affected by upstream rate
    # limits. The aggregator turns this into ``partial_results: ["mcpuniverse"]``
    # and ``degraded: true``, while still letting the (clean) score
    # contribute to the overall M2. Mirrors how locobench's checkpoint
    # fallback is reported.
    partial_reason = None
    if rate_limited_domains:
        partial_reason = (
            f"upstream rate limits affected {len(rate_limited_domains)} "
            f"of {len(sub_scores)} mcpuniverse domain(s) "
            f"({', '.join(sorted(rate_limited_domains))}); "
            f"per-domain notes attached, score computed from clean tasks"
        )

    return BenchmarkResult(
        name="mcpuniverse",
        score=overall,
        sub_scores=sub_scores,
        raw_metrics=raw_metrics,
        status="success",
        notes=notes,
        partial_reason=partial_reason,
    )


# ---------------------------------------------------------------------------
# MCPEval
# ---------------------------------------------------------------------------

def _mcpeval_analysis_file(bench_dir: Path, domain: str, model: str) -> Path:
    model_file_component = safe_filename_component(model)
    return bench_dir / f"benchmarks/{domain}/results/unified_{model_file_component}_analysis.json"


# Analysis script run inside MCPEval's venv: compares the model's
# per-task tool calls against the domain's verified ground truth using both
# strict and flexible matching, and writes an analysis JSON that
# score_mcpeval() reads back.
_MCPEVAL_ANALYSIS_SCRIPT = """
import json, sys
from mcpeval.metrics.static_tool_eval import (
    evaluate_tool_calls_with_both_match_types,
)

ground_truth = sys.argv[1]
predictions = sys.argv[2]
output = sys.argv[3]
evaluate_tool_calls_with_both_match_types(ground_truth, predictions, output)
print(f'[mcpeval.analysis] wrote {output}')
"""


def run_mcpeval(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["mcpeval"]
    profile = mode_profile(bench, mode)
    domains = mode_items(bench, mode, "domains")
    # Same opt-in gating as mcpuniverse: domains listed in
    # ``optional_domains`` whose required env vars are unset are skipped
    # with a note rather than failing the run. The MCP server for those
    # domains (e.g. mcp-server-nationalparks) would otherwise 401 on every
    # tool call and turn the score into noise. score_mcpeval surfaces the
    # skip notes in the aggregate report.
    num_tasks = profile["num_tasks"]
    max_turns = profile["max_turns"]
    bench_dir = REPO_ROOT / bench["dir"]
    venv_dir = str(REPO_ROOT / bench["venv"])
    env_overrides = {"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url}
    timeout_seconds = default_subprocess_timeout(config, mode)

    skipped = _skipped_optional_domains(bench, domains)
    runnable = [d for d in domains if d not in skipped]

    if skipped and tracker:
        for domain, missing in skipped.items():
            tracker.update("mcpeval", "running", f"skip {domain}: missing {','.join(missing)}")
    if skipped and log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a") as lf:
            for domain, missing in skipped.items():
                lf.write(f"[mcpeval] skipping domain '{domain}': missing env vars {missing}\n")

    for i, domain in enumerate(runnable):
        if tracker:
            tracker.update("mcpeval", "running", f"domain {i + 1}/{len(runnable)}: {domain}")
        model_config_dir = str(bench_dir / f"benchmarks/{domain}/eval_models")
        os.makedirs(model_config_dir, exist_ok=True)

        model_file_component = safe_filename_component(model)
        model_config_file = os.path.join(model_config_dir, f"unified_{model_file_component}.json")
        # Reasoning models (Gemini 2.5 / 3, Claude 3.7 + 4.x, OpenAI o-series
        # + gpt-5*, deepseek-r1) burn most of their per-call output budget on
        # internal thinking tokens. The historic 4096 cap left zero room for
        # the visible reply, which surfaced as
        # ``Invalid response (response without tool call detected)`` for
        # every task on those models. Bump the cap (and switch to
        # ``max_completion_tokens`` for OpenAI reasoning models, which
        # reject ``max_tokens``) when we recognize the model name. See
        # ``egi_bench/reasoning_models.py`` for the canonical detection.
        #
        # OpenAI reasoning models additionally reject any non-default
        # ``temperature`` ("Only the default (1) value is supported"),
        # so omit it from the recorded config -- both to avoid the 400
        # if the proxy ever stops dropping it, and so the persisted
        # ``unified_<model>.json`` artifact accurately reflects what the
        # upstream actually ran. Non-OpenAI reasoning models (Gemini /
        # Claude / deepseek-r1) accept the near-deterministic 0.01 fine
        # and keep it for run-to-run reproducibility.
        eval_model_cfg = {
            "model": model,
            "base_url": base_url,
            "api_key": "dummy",
        }
        if not is_openai_reasoning_model(model):
            eval_model_cfg["temperature"] = 0.01
        if is_long_context_reasoning_model(model):
            token_key = (
                "max_completion_tokens"
                if is_openai_reasoning_model(model)
                else "max_tokens"
            )
            eval_model_cfg[token_key] = DEFAULT_REASONING_MAX_TOKENS
        else:
            eval_model_cfg["max_tokens"] = 4096
        with open(model_config_file, "w") as f:
            json.dump(eval_model_cfg, f, indent=2)

        output_file = f"benchmarks/{domain}/results/unified_{model_file_component}_evaluation.jsonl"
        os.makedirs(str(bench_dir / f"benchmarks/{domain}/results"), exist_ok=True)

        eval_cmd = (
            f"python -u eval.py --domain {domain} "
            f"--model-config {model_config_file} "
            f"--num-tasks {num_tasks} --max-turns {max_turns} "
            f"--output {output_file}"
        )
        run_in_venv(
            str(bench_dir),
            venv_dir,
            eval_cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="mcpeval",
            tracker=tracker,
        )

        # Analysis: compare the predictions JSONL to ground-truth JSONL using
        # MCPEval's static tool evaluator. Writes a per-domain analysis JSON
        # with strict + flexible overall_score that score_mcpeval reads.
        if tracker:
            tracker.update("mcpeval", "running", f"domain {i + 1}/{len(domains)}: {domain} (analysis)")
        ground_truth_path = str(bench_dir / f"data/{domain}/evaluation_tasks_verified.jsonl")
        predictions_path = str(bench_dir / output_file)
        analysis_path = str(_mcpeval_analysis_file(bench_dir, domain, model))
        if not os.path.exists(predictions_path):
            # eval.py failed hard for this domain; let score_mcpeval flag it.
            continue
        # Quote paths defensively — they contain no spaces today, but the script
        # argv sits on the shell command line.
        analysis_cmd = (
            f"python -u -c {shlex.quote(_MCPEVAL_ANALYSIS_SCRIPT)} "
            f"{shlex.quote(ground_truth_path)} "
            f"{shlex.quote(predictions_path)} "
            f"{shlex.quote(analysis_path)}"
        )
        run_in_venv(
            str(bench_dir),
            venv_dir,
            analysis_cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="mcpeval",
            tracker=tracker,
        )


def score_mcpeval(config: dict, model: str, mode: str) -> BenchmarkResult:
    """Score MCPEval from the per-domain analysis JSONs written in run_mcpeval.

    Primary metric: flexible `average_score` (continuous, 0-100). This reflects
    how close the model's tool-call sequence came to ground truth, weighted
    across name / parameter / order components. Strict success rate is kept in
    raw_metrics for inspection but not used as the headline — it's too punishing
    for multi-step domains where partial credit matters.
    """
    bench = config["benchmarks"]["mcpeval"]
    domains = mode_items(bench, mode, "domains")
    bench_dir = REPO_ROOT / bench["dir"]
    # Mirror score_mcpuniverse: skipped opt-in domains are excluded from
    # the loop (so a stale analysis file from a previous run when the env
    # var was set doesn't sneak back in) and reported as notes.
    skipped = _skipped_optional_domains(bench, domains)
    sub_scores: Dict[str, float] = {}
    raw: Dict[str, dict] = {}
    notes: List[str] = []
    for domain in domains:
        if domain in skipped:
            continue
        analysis_file = _mcpeval_analysis_file(bench_dir, domain, model)
        if not analysis_file.exists():
            continue
        try:
            with open(analysis_file) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        stats = data.get("overall_stats") or {}
        flex = stats.get("flexible") or {}
        strict = stats.get("strict") or {}
        flex_score = flex.get("average_score")
        if flex_score is None:
            continue
        # overall_score/average_score is 0-1; convert to percentage for M1-M6.
        sub_scores[domain] = round(flex_score * 100, 2)
        raw[domain] = {
            "total_tasks": stats.get("total_tasks"),
            "flexible_average_score": round(flex_score * 100, 2),
            "flexible_success_rate": round((flex.get("success_rate") or 0) * 100, 2),
            "flexible_tool_name_accuracy": round((flex.get("tool_name_accuracy") or 0) * 100, 2),
            "flexible_param_match_accuracy": round((flex.get("param_match_accuracy") or 0) * 100, 2),
            "flexible_order_score": round((flex.get("order_score") or 0) * 100, 2),
            "strict_average_score": round((strict.get("average_score") or 0) * 100, 2),
            "strict_success_rate": round((strict.get("success_rate") or 0) * 100, 2),
        }

    notes.extend(
        f"skipped '{domain}' (opt-in): set {', '.join(missing)} to enable"
        for domain, missing in sorted(skipped.items())
    )

    if not sub_scores:
        if skipped and len(skipped) == len(domains):
            return BenchmarkResult(
                name="mcpeval",
                score=0,
                status="error",
                error_message=(
                    "All configured mcpeval domains were skipped for missing "
                    "credentials. Set the required env vars or trim "
                    "`optional_domains` in benchmark_config.yaml."
                ),
                notes=notes,
            )
        return BenchmarkResult(
            name="mcpeval",
            score=0,
            status="error",
            error_message=(
                "No MCPEval analysis outputs found. run_mcpeval must produce "
                "benchmarks/<domain>/results/unified_<model>_analysis.json via the "
                "static tool evaluator."
            ),
            notes=notes,
        )
    overall = round(sum(sub_scores.values()) / len(sub_scores), 2)
    if skipped:
        raw["_skipped_domains"] = {d: sorted(m) for d, m in skipped.items()}
    return BenchmarkResult(
        name="mcpeval",
        score=overall,
        sub_scores=sub_scores,
        raw_metrics=raw,
        status="success",
        notes=notes,
    )


# ---------------------------------------------------------------------------
# BenchForce
# ---------------------------------------------------------------------------

def run_benchforce(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["benchforce"]
    profile = mode_profile(bench, mode)
    environments = mode_items(bench, mode, "environments")
    defaults = bench["default_args"]
    entries_config = profile.get("entries", -1)
    # Benchforce can be slow on long hospital/HR sessions and run_benchforce.py
    # only writes results_*.json after the entire environment finishes, so a
    # too-tight wall-clock causes a SIGKILL with no scoreable output. Per-mode
    # ``timeout_seconds`` overrides the global default in
    # ``defaults.subprocess_timeout_seconds``.
    timeout_seconds = int(profile.get("timeout_seconds", default_subprocess_timeout(config, mode)))
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    env_overrides = {"OPENAI_API_KEY": "dummy", "OPENAI_BASE_URL": base_url}
    for i, environment in enumerate(environments):
        if tracker:
            tracker.update("benchforce", "running", f"env {i + 1}/{len(environments)}: {environment}")
        # entries_config=-1 means all; positive N means run entries 1..N (first N tasks)
        if entries_config == -1:
            entries_arg = "-1"
        else:
            entries_arg = " ".join(str(j) for j in range(1, int(entries_config) + 1))
        cmd = (
            f"python -u run_benchforce.py --environment {environment} --model {model} --base-url {base_url} "
            f"--api-key dummy --max-turns {defaults['max_turns']} --results-dir results/unified/{model} --entries {entries_arg}"
        )
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides=env_overrides,
            log_file=log_file,
            label="benchforce",
            tracker=tracker,
        )


def score_benchforce(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench = config["benchmarks"]["benchforce"]
    environments = mode_items(bench, mode, "environments")
    result_dir = REPO_ROOT / bench["dir"] / f"results/unified/{model}"
    sub_scores = {}
    for env_name in environments:
        # run_benchforce.py appends model/environment to results-dir, so check both paths
        result_files = sorted(glob.glob(str((result_dir / model / env_name) / "results_*.json")))
        if not result_files:
            result_files = sorted(glob.glob(str((result_dir / env_name) / "results_*.json")))
        if not result_files:
            continue
        with open(result_files[-1]) as f:
            data = json.load(f)
        accuracy_data = data.get("accuracy", {})
        if accuracy_data:
            sub_scores[f"{env_name}_accuracy_all"] = round(accuracy_data.get("accuracy_all", 0) * 100, 2)
            sub_scores[f"{env_name}_accuracy_finished"] = round(accuracy_data.get("accuracy_finished", 0) * 100, 2)
            sub_scores[f"{env_name}_all_entries"] = accuracy_data.get("total_entries", 0)
            sub_scores[f"{env_name}_finished_entries"] = accuracy_data.get("finished_entries", 0)
    if not sub_scores:
        return BenchmarkResult(name="benchforce", score=0, status="error", error_message=f"No Benchforce results in {result_dir}")
    acc_scores = [v for k, v in sub_scores.items() if k.endswith("_accuracy_all")]
    overall = round(sum(acc_scores) / len(acc_scores), 2) if acc_scores else 0.0
    return BenchmarkResult(name="benchforce", score=overall, sub_scores=sub_scores, raw_metrics=dict(sub_scores), status="success")


# ---------------------------------------------------------------------------
# LoCoBench
# ---------------------------------------------------------------------------

def run_locobench(config: dict, model: str, base_url: str, mode: str, log_file: Optional[str] = None, tracker=None):
    bench = config["benchmarks"]["locobench"]
    profile = mode_profile(bench, mode)
    categories = profile.get("task_categories", [])
    difficulty = profile.get("difficulty")
    max_concurrent = profile.get("max_concurrent_scenarios", bench["default_args"].get("max_concurrent_scenarios", 2))
    # Per-mode ``timeout_seconds`` overrides the global default in
    # ``defaults.subprocess_timeout_seconds``. Default keeps slow local
    # gateways from being SIGKILL'd mid-run on long deep sweeps.
    timeout_seconds = int(profile.get("timeout_seconds", default_subprocess_timeout(config, mode)))
    num_scenarios = profile.get("num_scenarios")
    bench_dir = str(REPO_ROOT / bench["dir"])
    venv_dir = str(REPO_ROOT / bench["venv"])
    runs = categories if categories else [None]
    for i, category in enumerate(runs):
        suffix = category or "all"
        out_file = f"evaluation_results/unified_{model}_{mode}_{suffix}.json"
        cmd = f"python run_eval_litellm.py --model {model} --max-concurrent-scenarios {max_concurrent} --output-file {out_file}"
        cmd += " --no-resume"
        if difficulty:
            cmd += f" --difficulty {difficulty}"
        else:
            cmd += " --full"
        if category:
            cmd += f" --task-category {category}"
        if num_scenarios:
            cmd += f" --num-scenarios {num_scenarios}"
        if tracker:
            tracker.update("locobench", "running", f"run {i + 1}/{len(runs)}: {suffix}")
        run_in_venv(
            bench_dir,
            venv_dir,
            cmd,
            timeout=timeout_seconds,
            env_overrides={
                "OPENAI_API_KEY": "dummy",
                "OPENAI_BASE_URL": base_url,
                "NO_PROXY": "localhost,127.0.0.1,0.0.0.0",
                "no_proxy": "localhost,127.0.0.1,0.0.0.0",
            },
            log_file=log_file,
            label="locobench",
            tracker=tracker,
        )


def _locobench_score_from_checkpoint(
    bench_dir: Path, model: str
) -> Optional[BenchmarkResult]:
    """Fallback scorer: parse LoCoBench's checkpoint + JSONL when the final
    ``unified_*.json`` is missing (e.g. the run was killed by the timeout).

    Returns ``None`` when no usable checkpoint exists, so the caller can fall
    back to the standard "no results" error path.
    """
    # Must match LoCoBenchEvaluator.__init__'s ``safe_model_name`` so we read
    # back what the evaluator wrote. The lower-casing matters on case-
    # insensitive filesystems (macOS HFS+, Windows NTFS) where ``GPT-4o`` and
    # ``gpt-4o`` would otherwise collide on the same checkpoint.
    model_norm = re.sub(r"[^A-Za-z0-9]", "_", model).lower()
    cp_path = bench_dir / "intermediate_results" / f"evaluation_checkpoint_{model_norm}.json"
    inc_path = bench_dir / "intermediate_results" / f"evaluation_incremental_results_{model_norm}.json"
    if not cp_path.exists() or not inc_path.exists():
        return None

    try:
        with open(cp_path) as f:
            cp = json.load(f)
    except Exception:
        return None

    completed = cp.get("completed_evaluations", {}).get(model)
    if isinstance(completed, dict):
        completed_set = set(completed.keys())
    elif isinstance(completed, list):
        completed_set = set(completed)
    else:
        completed_set = set()
    total_planned = int(cp.get("total_scenarios") or len(cp.get("scenarios") or []) or 0)

    started_at = cp.get("started_at") or ""

    latest_per_scenario: Dict[str, dict] = {}
    try:
        with open(inc_path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except Exception:
                    continue
                if rec.get("model_name") != model:
                    continue
                sid = rec.get("scenario_id")
                if not sid:
                    continue
                if completed_set and sid not in completed_set:
                    continue
                if started_at and (rec.get("timestamp") or "") < started_at:
                    continue
                prev = latest_per_scenario.get(sid)
                if prev is None or (rec.get("timestamp") or "") > (prev.get("timestamp") or ""):
                    latest_per_scenario[sid] = rec
    except Exception:
        return None

    records = list(latest_per_scenario.values())
    if not records:
        return None

    dims: Dict[str, list] = defaultdict(list)
    for rec in records:
        dims["software_engineering"].append(float(rec.get("software_engineering_score", 0)) * 100)
        dims["functional_correctness"].append(float(rec.get("functional_correctness_score", 0)) * 100)
        dims["code_quality"].append(float(rec.get("code_quality_score", 0)) * 100)
        dims["longcontext_utilization"].append(float(rec.get("longcontext_utilization_score", 0)) * 100)

    sub_scores = {k: round(sum(v) / len(v), 2) for k, v in dims.items() if v}
    if not sub_scores:
        return None
    overall = round(sum(sub_scores.values()) / len(sub_scores), 2)
    n = len(records)
    denom = total_planned if total_planned else n
    reason = f"scored from checkpoint at {n}/{denom} scenarios (final unified results missing)"
    return BenchmarkResult(
        name="locobench",
        score=overall,
        sub_scores=sub_scores,
        raw_metrics=dict(sub_scores),
        status="success",
        partial_reason=reason,
    )


def score_locobench(config: dict, model: str, mode: str) -> BenchmarkResult:
    bench = config["benchmarks"]["locobench"]
    bench_dir = REPO_ROOT / bench["dir"]
    out_dir = bench_dir / "evaluation_results"
    files = sorted(glob.glob(str(out_dir / f"unified_{model}_{mode}_*.json")), key=os.path.getmtime)
    if not files:
        partial = _locobench_score_from_checkpoint(bench_dir, model)
        if partial is not None:
            return partial
        return BenchmarkResult(name="locobench", score=0, status="error", error_message=f"No LoCoBench results in {out_dir}")
    dims = defaultdict(list)
    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)
            summaries = data.get("summaries", {})
            if not summaries:
                continue
            summary = next(iter(summaries.values()))
            dims["software_engineering"].append(float(summary.get("avg_software_engineering_score", 0)) * 100)
            dims["functional_correctness"].append(float(summary.get("avg_functional_correctness_score", 0)) * 100)
            dims["code_quality"].append(float(summary.get("avg_code_quality_score", 0)) * 100)
            dims["longcontext_utilization"].append(float(summary.get("avg_longcontext_utilization_score", 0)) * 100)
        except Exception:
            continue
    sub_scores = {k: round(sum(v) / len(v), 2) for k, v in dims.items() if v}
    if not sub_scores:
        partial = _locobench_score_from_checkpoint(bench_dir, model)
        if partial is not None:
            return partial
        return BenchmarkResult(name="locobench", score=0, status="error", error_message="No LoCoBench summary metrics parsed")
    overall = round(sum(sub_scores.values()) / len(sub_scores), 2)
    return BenchmarkResult(name="locobench", score=overall, sub_scores=sub_scores, raw_metrics=dict(sub_scores), status="success")


# ---------------------------------------------------------------------------
# Aggregation and reporting
# ---------------------------------------------------------------------------

# EGI Score = weighted mean of M1-M6.
# Definitions and weights mirror the "Six Dimensions" table in
# docs/scoring.md. These are the *defaults* used when
# ``benchmark_config.yaml`` omits an ``egi_weights:`` block; users
# normally tune the weights via that block (or per-invocation via the
# ``--egi-weights`` CLI flag) without touching this constant.
DEFAULT_EGI_WEIGHTS = {
    "M1": 0.28,  # Task Outcome Accuracy
    "M2": 0.22,  # Tool Actioning Reliability
    "M3": 0.16,  # Planning & Workflow Orchestration
    "M4": 0.14,  # Retrieval & Evidence Grounding
    "M5": 0.14,  # Safety, Abstention & Policy Compliance
    "M6": 0.06,  # Engineering & Maintainability Quality
}

EGI_METRIC_NAMES = tuple(DEFAULT_EGI_WEIGHTS.keys())

EGI_METRIC_DESCRIPTIONS = {
    "M1": "Task Outcome Accuracy",
    "M2": "Tool Actioning Reliability",
    "M3": "Planning & Workflow Orchestration",
    "M4": "Retrieval & Evidence Grounding",
    "M5": "Safety, Abstention & Policy Compliance",
    "M6": "Engineering & Maintainability Quality",
}


def _route_sub_metrics_to_egi(
    results: Dict[str, "BenchmarkResult"],
) -> Dict[str, List[Dict]]:
    """Route each benchmark's exposed sub_scores into M1-M6 buckets.

    The routing table comes straight from the "Where Each Number Comes From"
    section of docs/scoring.md. Only sub-scores that are actually emitted by
    the current runner are routed; sub-scores that aren't yet surfaced (e.g.
    HERB's "answerable non-null rate") are simply not included, per
    Aggregation Rule #4 (skip missing, reweight within bucket).

    Returns a dict of M -> list of {name, value, source} contributors.
    """
    buckets: Dict[str, List[Dict]] = {m: [] for m in EGI_METRIC_NAMES}

    def contribute(bucket: str, name: str, source: str, value):
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        buckets[bucket].append({"name": name, "source": source, "value": v})

    # Map CRMArena task acronyms to buckets.
    CRM_BUCKETS = {
        "NCR": "M1", "HTU": "M1", "TCU": "M1", "TII": "M1", "BRI": "M1", "MTA": "M1",
        "NED": "M4", "KQA": "M4",
        "PVI": "M5",
    }

    for bench_name, r in results.items():
        if r is None or r.status != "success":
            continue
        subs = r.sub_scores or {}

        if bench_name == "crmarena":
            for key, val in subs.items():
                bucket = CRM_BUCKETS.get(key)
                if bucket:
                    contribute(bucket, key, "crmarena", val)

        elif bench_name == "herb":
            for key, val in subs.items():
                # Keys look like "BAAI_...-model-N-ans_person" or "..._unanswerable".
                # Answerable splits → M4 (evidence/extraction quality).
                # Unanswerable null-rate → M5 (anti-hallucination).
                if key.endswith("_unanswerable"):
                    contribute("M5", key, "herb", val)
                elif "-ans_" in key:
                    contribute("M4", key, "herb", val)

        elif bench_name == "personabench":
            # All current sub-scores are (noise, question_type) QA accuracy
            # → M4 per roadmap ("QA accuracy, persona consistency"). The
            # roadmap also expects a multi-turn "context utilization" score
            # in M3; it's not exposed by the scorer today, so M3 skips it.
            for key, val in subs.items():
                contribute("M4", key, "personabench", val)

        elif bench_name == "userbench":
            # Per-env micro_avg → M3 (multi-turn planning quality).
            for key, val in subs.items():
                if key.endswith("_micro_avg"):
                    contribute("M3", key, "userbench", val)

        elif bench_name == "mcpuniverse":
            # Per-domain pass rates → M2. Quick mode exposes only
            # `financial_analysis`; deep mode adds `web_search`, etc.
            for key, val in subs.items():
                contribute("M2", f"pass_{key}", "mcpuniverse", val)

        elif bench_name == "mcpeval":
            # The decomposed components (tool_name / param / order / strict)
            # live inside `<domain>_analysis.json` but aren't exposed in
            # `sub_scores` today. For now route the per-domain flexible
            # average to M2 as the dominant signal (tool actioning).
            for key, val in subs.items():
                contribute("M2", f"flex_{key}", "mcpeval", val)

        elif bench_name == "benchforce":
            # Group by env: accuracy_all → M1; finished ratio → M2;
            # (accuracy_finished - accuracy_all) gap → M5 (unsafe-failure proxy).
            envs = set()
            for key in subs:
                if key.endswith("_accuracy_all"):
                    envs.add(key[: -len("_accuracy_all")])
            for env in envs:
                acc_all = subs.get(f"{env}_accuracy_all")
                acc_fin = subs.get(f"{env}_accuracy_finished")
                finished = subs.get(f"{env}_finished_entries")
                total = subs.get(f"{env}_all_entries")
                contribute("M1", f"{env}_accuracy_all", "benchforce", acc_all)
                if total and finished is not None:
                    try:
                        ratio = float(finished) / float(total) * 100.0
                        contribute("M2", f"{env}_finished_ratio", "benchforce", ratio)
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
                if acc_all is not None and acc_fin is not None:
                    gap = float(acc_fin) - float(acc_all)
                    # Larger gap = more unfinished-and-therefore-unsafe.
                    # Score is 100 - gap so "low gap" is high M5.
                    contribute("M5", f"{env}_safety_1_minus_gap",
                               "benchforce", max(0.0, 100.0 - gap))

        elif bench_name == "locobench":
            for key, val in subs.items():
                if key == "functional_correctness":
                    contribute("M1", key, "locobench", val)
                elif key == "longcontext_utilization":
                    contribute("M3", key, "locobench", val)
                elif key in ("software_engineering", "code_quality"):
                    contribute("M6", key, "locobench", val)

    return buckets


def compute_egi_metrics(
    results: Dict[str, "BenchmarkResult"],
    egi_weights: Optional[Dict[str, float]] = None,
) -> Dict:
    """Compute M1-M6 and the composite EGI Score from per-benchmark sub_scores.

    ``egi_weights`` is the per-bucket weight map (keys ``M1..M6``). If ``None``
    the module-level ``DEFAULT_EGI_WEIGHTS`` is used. Weights do not need to
    sum to 1.0: empty buckets are excluded and remaining weights are
    renormalized (Aggregation Rule #4 in docs/scoring.md).

    Each bucket is the equal-weighted mean of its contributors (Aggregation
    Rule #2). Missing sub-metrics are simply skipped; buckets with no
    contributors are flagged but do not zero out the EGI Score.
    """
    weights = egi_weights if egi_weights is not None else DEFAULT_EGI_WEIGHTS
    buckets = _route_sub_metrics_to_egi(results)

    per_metric: Dict[str, Dict] = {}
    for m in EGI_METRIC_NAMES:
        weight = weights.get(m, DEFAULT_EGI_WEIGHTS[m])
        contribs = buckets[m]
        if contribs:
            score = sum(c["value"] for c in contribs) / len(contribs)
            per_metric[m] = {
                "score": round(score, 2),
                "weight": weight,
                "description": EGI_METRIC_DESCRIPTIONS[m],
                "contributors": contribs,
            }
        else:
            per_metric[m] = {
                "score": None,
                "weight": weight,
                "description": EGI_METRIC_DESCRIPTIONS[m],
                "contributors": [],
            }

    active = {m: d for m, d in per_metric.items() if d["score"] is not None}
    total_w = sum(d["weight"] for d in active.values())
    if total_w > 0:
        egi = sum(d["score"] * d["weight"] for d in active.values()) / total_w
        egi = round(egi, 2)
    else:
        egi = None
    missing = [m for m, d in per_metric.items() if d["score"] is None]

    return {
        "egi_score": egi,
        "egi_metrics": per_metric,
        "missing_egi_metrics": missing,
    }


def aggregate_scores(
    results: Dict[str, BenchmarkResult],
    model: str,
    mode: str,
    required_benchmarks: List[str],
    run_kind: str = "run",
    total_runtime_seconds: Optional[float] = None,
    egi_weights: Optional[Dict[str, float]] = None,
) -> dict:
    missing_metrics = []
    missing_contributors = []
    partial_results = []
    degraded_reasons = []
    for name in required_benchmarks:
        result = results.get(name)
        if result is None or result.status != "success":
            missing_metrics.append(name)
            degraded_reasons.append(f"{name}: benchmark failed or missing")
        elif not result.sub_scores:
            missing_contributors.append(name)
            degraded_reasons.append(f"{name}: no sub-scores emitted")
        elif result.partial_reason:
            partial_results.append(name)
            degraded_reasons.append(f"{name}: {result.partial_reason}")

    degraded = bool(missing_metrics or missing_contributors or partial_results)

    # M1-M6 EGI decomposition. Routed from per-benchmark sub_scores per
    # docs/scoring.md; see compute_egi_metrics() for the mapping and
    # aggregation rules.
    egi_block = compute_egi_metrics(results, egi_weights=egi_weights)

    return {
        "model": model,
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        # ``run_kind`` records whether this report came from a fresh benchmark
        # execution (``"run"``) or from re-scoring cached outputs
        # (``"rescore"``). Subsequent rescores look this up so they don't
        # propagate the (essentially zero) scoring time as ``runtime_seconds``.
        "run_kind": run_kind,
        # EGI Score: 0.28*M1 + 0.22*M2 + 0.16*M3 + 0.14*M4 + 0.14*M5 + 0.06*M6,
        # renormalized over whichever buckets have contributors. ``None``
        # means no M-bucket had any routable sub-score.
        "egi_score": egi_block["egi_score"],
        "egi_metrics": egi_block["egi_metrics"],
        "missing_egi_metrics": egi_block["missing_egi_metrics"],
        # Wall-clock time of the full benchmark execution (parallel-aware: this
        # is end-to-end runtime of the dispatch loop, not the sum of per-domain
        # ``runtime_seconds`` which would over-count when benchmarks run in
        # parallel). ``None`` when unknown — e.g. when re-scoring (``--skip-run``)
        # and no prior real-run report has a recorded total to inherit.
        "total_runtime_seconds": (
            round(total_runtime_seconds, 1)
            if total_runtime_seconds is not None
            else None
        ),
        "degraded": degraded,
        "missing_metrics": missing_metrics,
        "missing_contributors": missing_contributors,
        "partial_results": partial_results,
        "degraded_reasons": degraded_reasons,
        "domain_scores": {
            name: {
                "score": r.score,
                "sub_scores": r.sub_scores,
                "status": r.status,
                "error_message": r.error_message,
                "runtime_seconds": (
                    round(r.runtime_seconds, 1)
                    if r.runtime_seconds is not None
                    else None
                ),
                **({"notes": r.notes} if r.notes else {}),
                **({"partial_reason": r.partial_reason} if r.partial_reason else {}),
            }
            for name, r in results.items()
        },
    }


def print_summary(report: dict):
    model = report["model"]
    print(f"\n{'=' * 78}")
    print(f"  EGI-Bench Results: {model} ({report['mode']} mode)")
    if report.get("degraded"):
        print("  STATUS: DEGRADED (soft-fail)")
    print(f"{'=' * 78}")
    print(f"  {'Domain':<20} {'Score':>8} {'Status':>10}")
    print(f"  {'-' * 50}")
    notes_by_domain = []
    for name, detail in sorted(report["domain_scores"].items()):
        score_str = f"{detail['score']:.1f}%" if detail["status"] == "success" else "  --"
        status_label = detail["status"]
        if detail.get("partial_reason"):
            status_label = "partial"
        print(f"  {name:<20} {score_str:>8} {status_label:>10}")
        domain_notes = list(detail.get("notes") or [])
        if detail.get("partial_reason"):
            domain_notes.append(f"partial: {detail['partial_reason']}")
        if domain_notes:
            notes_by_domain.append((name, domain_notes))

    # EGI Score (M1-M6).
    egi = report.get("egi_score")
    egi_metrics = report.get("egi_metrics") or {}
    if egi is not None or egi_metrics:
        print(f"  {'-' * 58}")
        for m in ("M1", "M2", "M3", "M4", "M5", "M6"):
            d = egi_metrics.get(m) or {}
            score = d.get("score")
            weight = d.get("weight", 0)
            desc = d.get("description", "")
            score_str = f"{score:.1f}%" if score is not None else "  --"
            print(f"  {m + ':':<5}{desc:<42} {score_str:>6}  w={weight:.0%}")
        if egi is not None:
            print(f"  {'-' * 58}")
            print(f"  {'EGI Score':<53} {egi:.1f}%")

    total_rt = report.get("total_runtime_seconds")
    if total_rt is not None:
        if total_rt >= 3600:
            rt_str = f"{total_rt / 3600:.2f}h ({total_rt:.1f}s)"
        elif total_rt >= 60:
            rt_str = f"{total_rt / 60:.1f}m ({total_rt:.1f}s)"
        else:
            rt_str = f"{total_rt:.1f}s"
        print(f"  {'TOTAL RUNTIME':<20} {rt_str:>15}")
    if report.get("degraded"):
        print(f"  {'DEGRADED REASONS':<20} {len(report.get('degraded_reasons', []))} issues")
    if notes_by_domain:
        print(f"  {'-' * 58}")
        for name, notes in notes_by_domain:
            for line in notes:
                print(f"  [{name}] {line}")
    print(f"{'=' * 78}")


def safe_filename_component(value: str) -> str:
    return value.replace("/", "_").replace(os.sep, "_").replace(":", "_")


def save_report(report: dict, output_dir: str) -> str:
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = safe_filename_component(str(report["model"]))
    filename = output_path / f"{model_name}_{report['mode']}_{ts}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    return str(filename)


def load_previous_runtimes(
    output_dir: str, model: str, mode: str, benchmarks: List[str]
) -> Dict[str, Optional[float]]:
    """Return ``runtime_seconds`` for each benchmark from prior real-run reports.

    Used by ``--skip-run`` so that re-scoring an existing run preserves the
    original wall-clock runtimes rather than reporting the (essentially zero)
    time it took to re-aggregate cached outputs.

    Only reports tagged ``run_kind == "run"`` are considered as runtime
    sources; rescored reports are skipped so we never inherit the bogus
    near-zero runtimes that ``--skip-run`` used to record. Reports without a
    ``run_kind`` field (legacy, pre-fix) are treated as real runs for
    backward compat. For each benchmark we walk eligible reports newest-first
    and pick the first positive runtime; if none is positive we fall back to
    the most recent recorded value (preserving ``None`` vs ``0.0``).
    """
    fallback = {name: None for name in benchmarks}
    if not os.path.isdir(output_dir):
        return fallback
    prefix = f"{model}_{mode}_"
    candidates = [
        f for f in os.listdir(output_dir)
        if f.endswith(".json") and f.startswith(prefix) and f != "latest.json"
    ]
    if not candidates:
        return fallback

    candidates.sort(
        key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
        reverse=True,
    )

    runtimes: Dict[str, Optional[float]] = {name: None for name in benchmarks}
    newest_seen: Dict[str, Optional[float]] = {name: None for name in benchmarks}
    seen_any: Dict[str, bool] = {name: False for name in benchmarks}
    resolved: Dict[str, bool] = {name: False for name in benchmarks}

    for filename in candidates:
        if all(resolved.values()):
            break
        try:
            with open(os.path.join(output_dir, filename)) as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            continue
        # Skip explicitly-rescored reports so their (zero) runtimes don't
        # poison subsequent rescores. Reports without ``run_kind`` predate
        # this fix and may be either real runs or rescores; we include them
        # for backward compatibility.
        if data.get("run_kind") == "rescore":
            continue
        domain_scores = data.get("domain_scores") or {}
        for name in benchmarks:
            if resolved[name]:
                continue
            rt_raw = (domain_scores.get(name) or {}).get("runtime_seconds")
            try:
                rt_val = float(rt_raw) if rt_raw is not None else None
            except (TypeError, ValueError):
                rt_val = None
            if not seen_any[name]:
                newest_seen[name] = rt_val
                seen_any[name] = True
            if rt_val is not None and rt_val > 0:
                runtimes[name] = rt_val
                resolved[name] = True

    for name in benchmarks:
        if not resolved[name]:
            runtimes[name] = newest_seen[name]
    return runtimes


def load_previous_total_runtime(
    output_dir: str, model: str, mode: str
) -> Optional[float]:
    """Return ``total_runtime_seconds`` from the most recent real-run report.

    Companion to :func:`load_previous_runtimes`: used by ``--skip-run`` so the
    rescored report inherits the original wall-clock total instead of the
    near-zero time it took to re-aggregate cached outputs. Reports tagged
    ``run_kind == "rescore"`` are skipped; legacy reports without ``run_kind``
    are treated as real runs for backward compat. Walks newest-first and
    returns the first positive total; if none is positive, returns the most
    recent recorded value (which may be ``None``).
    """
    if not os.path.isdir(output_dir):
        return None
    prefix = f"{model}_{mode}_"
    candidates = [
        f for f in os.listdir(output_dir)
        if f.endswith(".json") and f.startswith(prefix) and f != "latest.json"
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
        reverse=True,
    )

    newest_seen: Optional[float] = None
    seen_any = False
    for filename in candidates:
        try:
            with open(os.path.join(output_dir, filename)) as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("run_kind") == "rescore":
            continue
        raw = data.get("total_runtime_seconds")
        try:
            val = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            val = None
        if not seen_any:
            newest_seen = val
            seen_any = True
        if val is not None and val > 0:
            return val
    return newest_seen


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

RUNNERS = {
    "crmarena": (run_crmarena, score_crmarena),
    "herb": (run_herb, score_herb),
    "personabench": (run_personabench, score_personabench),
    "userbench": (run_userbench, score_userbench),
    "mcpuniverse": (run_mcpuniverse, score_mcpuniverse),
    "mcpeval": (run_mcpeval, score_mcpeval),
    "benchforce": (run_benchforce, score_benchforce),
    "locobench": (run_locobench, score_locobench),
}


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def parse_egi_weight_overrides(value: str) -> Dict[str, float]:
    """Parse a ``--egi-weights`` CLI value like ``M1=0.5,M5=0.2``.

    Only the listed M-buckets are returned; unspecified ones fall back to
    the config defaults at merge time. Keys must be one of ``M1..M6`` and
    values must be non-negative floats.
    """
    overrides: Dict[str, float] = {}
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            raise argparse.ArgumentTypeError("empty M-bucket entry")
        if "=" not in pair:
            raise argparse.ArgumentTypeError(f"expected M=VALUE, got {pair!r}")
        name, raw_weight = pair.split("=", 1)
        name = name.strip().upper()
        if name not in EGI_METRIC_NAMES:
            raise argparse.ArgumentTypeError(
                f"unknown EGI bucket {name!r}; valid: {', '.join(EGI_METRIC_NAMES)}"
            )
        try:
            weight = float(raw_weight.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid weight for {name!r}: {raw_weight!r}"
            ) from exc
        if weight < 0:
            raise argparse.ArgumentTypeError(
                f"weight for {name!r} must be non-negative"
            )
        overrides[name] = weight
    return overrides


def resolve_egi_weights(
    config: dict, overrides: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """Merge YAML defaults, ``benchmark_config.yaml::egi_weights``, and CLI overrides.

    Resolution order (later wins): ``DEFAULT_EGI_WEIGHTS`` → YAML
    ``egi_weights:`` block → CLI ``--egi-weights`` overrides. Validation
    happens here so a bad config or CLI value fails fast with a clear
    message before any benchmarks dispatch.
    """
    weights: Dict[str, float] = dict(DEFAULT_EGI_WEIGHTS)

    yaml_block = config.get("egi_weights")
    if yaml_block is not None:
        if not isinstance(yaml_block, dict):
            raise SystemExit(
                "benchmark_config.yaml: egi_weights must be a mapping of M1..M6 to numbers"
            )
        for raw_name, raw_value in yaml_block.items():
            name = str(raw_name).upper()
            if name not in EGI_METRIC_NAMES:
                raise SystemExit(
                    f"benchmark_config.yaml: unknown egi_weights key {raw_name!r}; "
                    f"valid: {', '.join(EGI_METRIC_NAMES)}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise SystemExit(
                    f"benchmark_config.yaml: egi_weights[{raw_name!r}] must be a number, "
                    f"got {raw_value!r}"
                ) from exc
            if value < 0:
                raise SystemExit(
                    f"benchmark_config.yaml: egi_weights[{raw_name!r}] must be non-negative"
                )
            weights[name] = value

    if overrides:
        weights.update(overrides)

    if sum(weights.values()) <= 0:
        raise SystemExit("egi_weights: at least one M-bucket must have a positive weight")

    return weights


def health_endpoint_for_base_url(config: dict, base_url: str, base_url_overridden: bool) -> str:
    if not base_url_overridden:
        return config["gateway"]["health_endpoint"]

    parsed = urllib.parse.urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit("--base-url must include scheme and host, for example http://localhost:8008/v1")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    else:
        path = ""
    # LiteLLM Proxy exposes /health/liveliness (lightweight, doesn't probe
    # upstream models, suitable for a startup readiness check).
    health_path = f"{path}/health/liveliness" if path else "/health/liveliness"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, health_path, "", ""))


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description=(
            "Run EGI-Bench benchmarks through the unified runner. "
            "By default, inference is sent to the local LiteLLM proxy "
            "endpoint configured in benchmark_config.yaml."
        ),
        epilog=(
            "Examples:\n"
            "  .venv/bin/python run_all.py --model gpt-4.1-mini --mode quick\n"
            "  .venv/bin/python run_all.py --model gpt-4.1-mini --mode quick --parallel --max-workers 2\n"
            "  .venv/bin/python run_all.py --model gpt-4.1-mini --mode quick --benchmarks herb userbench mcpeval\n"
            "  .venv/bin/python run_all.py --model gpt-4.1-mini --mode quick --skip-run\n"
            "\n"
            "Reports are written to results_aggregated/ by default. Per-benchmark "
            "logs are written under results_aggregated/logs/."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", required=True, help="Model name to evaluate, for example gpt-4.1-mini.")
    parser.add_argument(
        "--benchmarks",
        nargs="+",
        default=BENCHMARK_NAMES,
        choices=BENCHMARK_NAMES,
        help="One or more benchmarks to run. Defaults to all benchmarks.",
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "deep"],
        default="deep",
        help="Execution profile from benchmark_config.yaml. quick is smaller; deep is broader. Default: deep.",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Do not execute benchmark commands; only score existing result files.",
    )
    parser.add_argument(
        "--config",
        default="benchmark_config.yaml",
        help="Path to the unified benchmark configuration YAML. Default: benchmark_config.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        default="results_aggregated",
        help="Directory for aggregated reports and per-benchmark logs. Default: results_aggregated.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the OpenAI-compatible gateway base URL from config, for example http://localhost:8008/v1.",
    )
    parser.add_argument(
        "--egi-weights",
        type=parse_egi_weight_overrides,
        default=None,
        help=(
            "Per-invocation overrides for the M1-M6 EGI Score weights, "
            "e.g. M1=0.5,M5=0.2. Unspecified Ms keep their YAML default. "
            "Values need not sum to 1.0 (renormalized over non-empty buckets)."
        ),
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run selected benchmarks concurrently. Use --max-workers to cap concurrency.",
    )
    parser.add_argument(
        "--max-workers",
        type=positive_int,
        default=None,
        help="Maximum parallel benchmark workers when --parallel is set. Default: min(selected benchmarks, CPU count).",
    )
    args = parser.parse_args(argv)
    if args.max_workers is not None and not args.parallel:
        parser.error("--max-workers requires --parallel")
    return args


def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)
    config = load_config(args.config)
    mode = args.mode
    base_url = args.base_url or config["gateway"]["base_url"]
    health_endpoint = health_endpoint_for_base_url(config, base_url, args.base_url is not None)
    egi_weights = resolve_egi_weights(config, args.egi_weights)

    if not args.skip_run:
        # If the user pointed at an external proxy via --base-url, don't
        # try to manage its lifecycle — it lives somewhere else (Docker,
        # remote host, ...). Just verify it's healthy.
        if args.base_url:
            check_gateway_health(health_endpoint)
        elif _proxy_is_responsive(health_endpoint):
            # Reuse whatever's already on :8008. Common case: the user
            # ran `egi-bench proxy start` once and is now firing several
            # benchmark runs back-to-back.
            print("[run_all] Reusing existing litellm proxy on this host.")
        else:
            # Auto-spawn for the duration of this run, and tear down on
            # exit. We register cleanup with atexit (covers normal exit,
            # sys.exit, and KeyboardInterrupt-after-unwind) plus a SIGTERM
            # handler that forwards to sys.exit() so atexit still fires.
            start_proxy(health_endpoint)
            atexit.register(stop_proxy, quiet=True)
            signal.signal(signal.SIGTERM, lambda signum, _frame: sys.exit(128 + signum))
        check_gateway_inference_ready(base_url, args.model)
        # Aggregate venv preflight. Per-benchmark fail-fast still runs in
        # _run_one, but reporting every missing venv up-front lets the user
        # install them all in one pass instead of discovering them one by one.
        missing_venvs: List[str] = []
        for bench_name in args.benchmarks:
            venv_rel = config["benchmarks"].get(bench_name, {}).get("venv")
            if venv_rel and not (REPO_ROOT / venv_rel / "bin" / "python").exists():
                missing_venvs.append(f"{bench_name} -> {venv_rel}")
        if missing_venvs:
            print(
                "[run_all] Missing benchmark venvs:\n  "
                + "\n  ".join(missing_venvs)
                + "\n[run_all] Install them with `egi-bench setup` "
                "(or `cd <benchmark> && uv venv && uv pip install -r requirements.txt`). "
                "Affected benchmarks will be reported as errors in the aggregate; "
                "other benchmarks still run."
            )

    results: Dict[str, BenchmarkResult] = {}
    log_dir = os.path.join(args.output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_files = {name: os.path.join(log_dir, f"{name}_{mode}_{timestamp}.log") for name in args.benchmarks}
    tracker = ProgressTracker(args.benchmarks)
    print(f"[run_all] Logs directory: {log_dir}/")

    # When re-scoring without a fresh run, preserve the runtime from the most
    # recent matching aggregate report so the new report doesn't report 0.0
    # for the (skipped) benchmark execution.
    previous_runtimes: Dict[str, Optional[float]] = (
        load_previous_runtimes(args.output_dir, args.model, mode, args.benchmarks)
        if args.skip_run
        else {name: None for name in args.benchmarks}
    )

    def _runtime_for(bench_name: str, start: float) -> Optional[float]:
        if args.skip_run:
            return previous_runtimes.get(bench_name)
        return time.time() - start

    def _run_one(bench_name: str) -> BenchmarkResult:
        run_fn, score_fn = RUNNERS[bench_name]
        start = time.time()
        # Fail fast with a clear message if the benchmark's venv is missing.
        bench_cfg = config["benchmarks"].get(bench_name, {})
        venv_rel = bench_cfg.get("venv")
        if not args.skip_run and venv_rel:
            venv_python = REPO_ROOT / venv_rel / "bin" / "python"
            if not venv_python.exists():
                msg = (
                    f"venv not found at {venv_rel}. "
                    f"Install it with `cd {bench_cfg.get('dir', bench_name)} && uv venv && uv pip install ...` "
                    f"(see README Quick Start)."
                )
                result = BenchmarkResult(
                    name=bench_name, score=0, status="error",
                    error_message=msg, runtime_seconds=_runtime_for(bench_name, start),
                )
                tracker.update(bench_name, "error", f"venv missing: {venv_rel}")
                return result
        try:
            if not args.skip_run:
                tracker.update(bench_name, "running")
                run_fn(config, args.model, base_url, mode, log_file=log_files[bench_name], tracker=tracker)
            tracker.update(bench_name, "scoring")
            result = score_fn(config, args.model, mode)
            result.runtime_seconds = _runtime_for(bench_name, start)
            tracker.update(bench_name, "done", f"{result.score:.1f}%")
        except Exception as e:
            result = BenchmarkResult(
                name=bench_name, score=0, status="error", error_message=str(e),
                runtime_seconds=_runtime_for(bench_name, start),
            )
            tracker.update(bench_name, "error", str(e)[:60])
        return result

    total_start = time.time()
    if args.parallel and len(args.benchmarks) > 1:
        max_workers = args.max_workers or min(len(args.benchmarks), os.cpu_count() or 4)
        print(f"[run_all] Running {len(args.benchmarks)} benchmarks in parallel (max_workers={max_workers})")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_one, name): name for name in args.benchmarks}
            for future in as_completed(futures):
                bench_name = futures[future]
                try:
                    results[bench_name] = future.result()
                except Exception as e:
                    results[bench_name] = BenchmarkResult(name=bench_name, score=0, status="error", error_message=f"Executor error: {e}")
    else:
        for bench_name in args.benchmarks:
            results[bench_name] = _run_one(bench_name)
    total_elapsed = time.time() - total_start

    tracker.finish()
    print()
    # On --skip-run, the elapsed time above only covers re-aggregation of
    # cached outputs (~seconds), so inherit the prior real-run total instead.
    if args.skip_run:
        total_runtime = load_previous_total_runtime(args.output_dir, args.model, mode)
    else:
        total_runtime = total_elapsed
    report = aggregate_scores(
        results, args.model, mode, args.benchmarks,
        run_kind="rescore" if args.skip_run else "run",
        total_runtime_seconds=total_runtime,
        egi_weights=egi_weights,
    )
    print_summary(report)
    filepath = save_report(report, args.output_dir)
    print(f"Report saved to: {filepath}")
    print("\nDetailed logs:")
    for name in args.benchmarks:
        status = results.get(name)
        icon = "OK" if status and status.status == "success" else "!!"
        print(f"  [{icon}] {name}: {log_files[name]}")


if __name__ == "__main__":
    main()
