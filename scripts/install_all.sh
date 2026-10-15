#!/usr/bin/env bash
# One-shot installer for every benchmark.
#
# Setup order:
#   * Root .venv is always reconciled with requirements.txt for run_all.py.
#   * For each benchmark:
#       - If .venv already exists -> SKIP (idempotent; delete .venv to force reinstall).
#       - Otherwise create a venv and install dependencies.
#
# Individual failures do not abort the others; a summary is printed at the end.
# After all venvs succeed, download_data.sh is invoked to fetch any data bundles
# unless EGI_BENCH_SKIP_DATA=1 is set.

set -u  # intentionally not -e: we want to continue past per-benchmark failures.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is not installed. See https://github.com/astral-sh/uv" >&2
  exit 1
fi

echo "=== Installing unified runner dependencies"
# Reuse an existing root .venv (e.g. created earlier by `uv sync`) instead of
# recreating it; `uv venv` would otherwise prompt to overwrite and abort the
# whole setup if the user declines.
if [ ! -x .venv/bin/python ]; then
  if ! uv venv .venv; then
    echo "ERROR: failed to create root .venv" >&2
    exit 1
  fi
fi
if uv pip install --python .venv/bin/python -e . && \
   .venv/bin/python -c 'import yaml' && \
   [ -x .venv/bin/egi-bench ]; then
  echo "=== Unified runner ready (.venv/bin/egi-bench)"
else
  echo "ERROR: unified runner dependency install failed" >&2
  exit 1
fi
echo

echo "=== Installing litellm_proxy/.venv"
# The local LiteLLM proxy is the LLM entry point for every benchmark.
# Provision it alongside the root runner so `egi-bench run` can auto-spawn
# it without a manual install step. Idempotent: existing venv is kept.
if [ ! -x litellm_proxy/.venv/bin/litellm ]; then
  if ( cd litellm_proxy && unset VIRTUAL_ENV && uv venv && uv pip install -r requirements.txt ); then
    echo "=== litellm_proxy ready (litellm_proxy/.venv/bin/litellm)"
  else
    echo "ERROR: litellm_proxy dependency install failed" >&2
    exit 1
  fi
else
  echo "=== litellm_proxy: venv already present, skipping (delete litellm_proxy/.venv to reinstall)"
fi
echo

STATUS_OK=()
STATUS_SKIP=()
STATUS_FAIL=()

install_one() {
  local dir="$1"
  shift
  if [ ! -d "$dir" ]; then
    echo "--- $dir missing, skipping"
    STATUS_SKIP+=("$dir (directory missing)")
    return
  fi
  if [ -x "$dir/.venv/bin/python" ]; then
    echo "=== $dir: venv already present, skipping (delete $dir/.venv to reinstall)"
    STATUS_SKIP+=("$dir (already installed)")
    return
  fi
  echo "=== Installing $dir"
  # Unset VIRTUAL_ENV so `uv pip install` targets the per-benchmark `.venv`
  # rather than whichever venv the caller activated (e.g. the root .venv).
  if ( cd "$dir" && unset VIRTUAL_ENV && "$@" ); then
    STATUS_OK+=("$dir")
  else
    STATUS_FAIL+=("$dir")
    echo "!!! $dir install failed; continuing with the other benchmarks" >&2
  fi
}

install_one CRMArena bash -c 'uv venv && uv pip install -r requirements.txt'

install_one HERB bash -c 'uv venv && uv pip install -r requirements.txt'

install_one PersonaBench bash -c '
  uv venv
  if [ -f requirements-macos.txt ] && [ "$(uname)" = "Darwin" ]; then
    uv pip install -r requirements-macos.txt
  else
    uv pip install -r requirements.txt
  fi
  uv pip install -e .
'

install_one UserBench bash -c 'uv venv && uv pip install -r requirements.txt && uv pip install -e .'

install_one MCP-Universe bash -c 'uv venv && uv pip install -e .'

# MCPEval requires Python >= 3.12.
install_one MCPEval bash -c 'uv venv --python 3.12 && uv pip install -e . && uv pip install -r requirements.txt'

install_one Benchforce bash -c 'uv venv && uv pip install -r requirements_text.txt'

install_one LoCoBench bash -c 'uv venv && uv pip install -r requirements.txt && uv pip install -e .'

echo
echo "=============================== Install summary ==============================="
if [ ${#STATUS_OK[@]} -gt 0 ];   then echo "Installed: ${STATUS_OK[*]}";   fi
if [ ${#STATUS_SKIP[@]} -gt 0 ]; then echo "Skipped:   ${STATUS_SKIP[*]}"; fi
if [ ${#STATUS_FAIL[@]} -gt 0 ]; then echo "FAILED:    ${STATUS_FAIL[*]}"; fi
echo "==============================================================================="

# If any install failed, stop here so the user can fix it before data steps.
if [ ${#STATUS_FAIL[@]} -gt 0 ]; then
  echo
  echo "Fix the failures above, then re-run this script (already-installed benchmarks" >&2
  echo "are skipped, so it is safe to run repeatedly)." >&2
  exit 1
fi

# Continue to data downloads (LoCoBench scenarios).
if [ "${EGI_BENCH_SKIP_DATA:-0}" = "1" ]; then
  echo
  echo "=== Skipping data setup (EGI_BENCH_SKIP_DATA=1)"
  exit 0
fi

echo
echo "=== Running data setup (LoCoBench scenarios)"
exec "$REPO_ROOT/scripts/download_data.sh"
