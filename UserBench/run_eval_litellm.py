#!/usr/bin/env python3
"""
Wrapper script to run UserBench (TravelGym) evaluation via the LiteLLM proxy.
Sets up the environment to route all OpenAI API calls through the local proxy.
"""

import os
import sys
import subprocess

# Configure to use the LiteLLM proxy
os.environ['OPENAI_API_KEY'] = 'dummy'  # Required but not used by proxy
os.environ['OPENAI_API_BASE'] = 'http://localhost:8008/v1'
os.environ['OPENAI_BASE_URL'] = 'http://localhost:8008/v1'  # For newer OpenAI SDK versions

# Default settings for testing
# Note: gpt-5-nano requires temperature=1, use gpt-4o-mini for temperature=0.0
DEFAULT_ARGS = [
    '--model_name', 'gpt-4o-mini',
    '--port', '8009',
    '--max_turns', '5',  # Reduced for faster testing
    '--pass_k', '1',
    '--temperature', '0.0',
    '--envs', 'travel22',  # Start with simplest environment
    '--save_name', 'travel_litellm_test',
]

if __name__ == "__main__":
    # Use provided args or defaults
    args = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_ARGS

    # Run eval.py with configured environment
    cmd = ['uv', 'run', 'python', 'eval.py'] + args

    print("=" * 80)
    print("UserBench (TravelGym) Evaluation via LiteLLM proxy")
    print("=" * 80)
    print(f"Command: {' '.join(cmd)}")
    print(f"Gateway: {os.environ['OPENAI_BASE_URL']}")
    print("=" * 80)
    print()

    # Execute eval.py
    result = subprocess.run(cmd, env=os.environ.copy())
    sys.exit(result.returncode)
