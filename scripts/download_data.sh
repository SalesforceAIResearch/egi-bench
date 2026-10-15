#!/usr/bin/env bash
# Download benchmark-specific data bundles that pip cannot install.
#
# Currently covers:
#   * LoCoBench       - 250MB scenario bundle from Google Drive (no credentials).
#
# Both steps are idempotent: skipped when the expected output already exists.
# If a venv is missing, this script exits with a non-zero code pointing at
# scripts/install_all.sh — it will NOT silently skip.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load root .env (does not overwrite already-set vars) so optional credentials
# can be configured in one place.
_load_env_no_overwrite() {
  local file="$1"
  [ -f "$file" ] || return
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    val="${val#\"}" ; val="${val%\"}"
    val="${val#\'}" ; val="${val%\'}"
    [ -z "$key" ] || [ -z "$val" ] && continue
    [ -n "${!key+x}" ] && continue
    export "$key=$val"
  done < "$file"
}

_load_env_no_overwrite "$REPO_ROOT/.env"

missing_venvs=()
for dir in LoCoBench; do
  if [ ! -x "$dir/.venv/bin/python" ]; then
    missing_venvs+=("$dir")
  fi
done

if [ ${#missing_venvs[@]} -gt 0 ]; then
  echo "ERROR: venv missing for: ${missing_venvs[*]}" >&2
  echo "Run scripts/install_all.sh first." >&2
  exit 1
fi

exit_code=0

# ---------- LoCoBench -----------------------------------------------------
# Scenarios live under data/output/scenarios/ (run_eval_litellm.py:45).
locobench_data_ready() {
  [ -d "LoCoBench/data/output/scenarios" ] && \
    [ -n "$(find LoCoBench/data/output/scenarios -maxdepth 1 -type f -name '*.json' 2>/dev/null | head -1)" ]
}

if locobench_data_ready; then
  echo "[locobench] data/scenarios already present, skipping download"
else
  echo "[locobench] downloading 250MB scenario bundle from Google Drive..."
  if ( cd LoCoBench && \
       { .venv/bin/pip show gdown >/dev/null 2>&1 || uv pip install --python .venv/bin/python gdown; } && \
       .venv/bin/python -m gdown "https://drive.google.com/uc?id=1pK1M1sRrVZUDMKYcwh49CdXug0UzStvl" && \
       unzip -q -o data.zip && \
       rm data.zip ); then
    echo "[locobench] done"
  else
    echo "[locobench] FAILED (check network access to Google Drive)" >&2
    exit_code=1
  fi
fi

echo
if [ $exit_code -eq 0 ]; then
  echo "Data setup complete. Run benchmarks with:"
  echo "  egi-bench run --model <model> --mode quick --parallel"
else
  echo "Data setup finished with errors. Fix them above and re-run this script."
fi
exit $exit_code
