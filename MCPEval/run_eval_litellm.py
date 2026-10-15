#!/usr/bin/env python3
"""
Wrapper to run MCPEval evaluation via the LiteLLM proxy.

Sets up environment for the LiteLLM proxy and delegates to eval.py.
"""
import os
import sys
import subprocess

# Configure for LiteLLM proxy
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["OPENAI_BASE_URL"] = "http://localhost:8008/v1"

# Default arguments for quick testing
DEFAULT_ARGS = [
    "--domain", "airbnb",
    "--num-tasks", "5",
    "--max-turns", "10",
]

if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_ARGS
    script_dir = os.path.dirname(os.path.abspath(__file__))
    eval_script = os.path.join(script_dir, "eval.py")

    cmd = [sys.executable, eval_script] + args
    print(f"MCPEval Evaluation via LiteLLM proxy")
    print(f"Proxy:   {os.environ['OPENAI_BASE_URL']}")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=script_dir, env=os.environ.copy())
    sys.exit(result.returncode)
