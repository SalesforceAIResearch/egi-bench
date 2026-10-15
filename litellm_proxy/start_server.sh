#!/bin/bash
# Start the EGI-Bench LiteLLM Proxy on http://localhost:8008.
#
# Reads provider credentials from the repo-root .env (OPENAI_API_KEY,
# ANTHROPIC_API_KEY, GEMINI_API_KEY, VERTEX_PROJECT, VERTEX_LOCATION,
# AWS_*, ...) and the per-model routing from ./litellm_config.yaml.
#
# Run from anywhere — the script cd's to its own directory first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load the repo-root .env so per-provider keys are visible to LiteLLM.
# Keys already exported in the shell take precedence.
ROOT_ENV="$SCRIPT_DIR/../.env"
if [ -f "$ROOT_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ROOT_ENV"
    set +a
fi

# Default port matches benchmark_config.yaml::gateway.base_url.
PORT="${LITELLM_PROXY_PORT:-8008}"
HOST="${LITELLM_PROXY_HOST:-0.0.0.0}"

echo "[litellm_proxy] Starting on http://${HOST}:${PORT}/v1"
echo "[litellm_proxy] Config: $SCRIPT_DIR/litellm_config.yaml"

# Invoke the litellm CLI from this directory's venv directly so we don't
# accidentally run inside the parent egi-bench project's venv (which
# does not depend on litellm[proxy]).
LITELLM_BIN="$SCRIPT_DIR/.venv/bin/litellm"
if [ ! -x "$LITELLM_BIN" ]; then
    echo "[litellm_proxy] ERROR: $LITELLM_BIN not found." >&2
    echo "[litellm_proxy] Run: uv venv && uv pip install -r requirements.txt" >&2
    exit 1
fi

exec "$LITELLM_BIN" \
    --config litellm_config.yaml \
    --host "$HOST" \
    --port "$PORT"
