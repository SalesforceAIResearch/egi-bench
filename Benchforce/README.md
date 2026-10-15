# Benchforce (Text Mode)

Benchforce is a flexible, extensible framework for evaluating text- and voice-based agents in real time or multi-leg scenarios. **In this egi-bench integration, we use text mode only** to evaluate LLM function-calling capabilities across simulated enterprise environments.

**Source:** [SalesforceAIResearch/benchforce](https://github.com/SalesforceAIResearch/benchforce)

## Environments

| Environment      | Tasks  | Description                                                                                           |
| ---------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| hospital         | 64     | Healthcare workflows: appointments, medications, referrals, emergency transfers. 4 difficulty levels. |
| hr_software      | 28     | HR system operations: user management, permissions, subscriptions, downtime verification.             |
| **Total**        | **92** |                                                                                                       |

## Running via egi-bench (recommended)

Benchforce is registered as a benchmark in the [EGI-Bench](../README.md) suite.
From the repository root, after [`egi-bench setup`](../README.md#5-install-benchmark-environments)
provisions `Benchforce/.venv` and the [local LiteLLM proxy is running](../README.md#4-start-the-local-litellm-proxy):

```bash
# Quick mode: hospital only, 40 entries
egi-bench run --model gpt-4o-mini --mode quick --benchmarks benchforce

# Deep mode: hospital + hr_software, all entries
egi-bench run --model gpt-4o-mini --mode deep --benchmarks benchforce
```

Per-mode environment list, entry caps, and `max_turns` live in
[`benchmark_config.yaml`](../benchmark_config.yaml) under
`benchmarks.benchforce`.

## Standalone Setup

Use these steps only when developing Benchforce in isolation;
`egi-bench setup` already runs the `uv venv` + `uv pip install` pair for
you.

```bash
cd Benchforce
uv venv
uv pip install -r requirements_text.txt
```

### Standalone evaluation

```bash
cd Benchforce

# Run hospital environment (all 64 entries)
uv run python run_benchforce.py \
    --environment hospital \
    --model gpt-4o-mini \
    --base-url http://localhost:8008/v1

# Run specific entries (1-based)
uv run python run_benchforce.py \
    --environment hospital \
    --model gpt-4o-mini \
    --base-url http://localhost:8008/v1 \
    --entries 1 2 3
```

## Architecture

In text mode, the framework:

1. Spins up a WebSocket server for agent-client communication
2. The **client** sends task instructions as text messages
3. The **agent** (OpenAI-compatible LLM) processes messages and makes function calls
4. Function calls execute against simulated environment data
5. Accuracy is measured by comparing function call results to ground truth

## Metrics

- **Accuracy (All):** Fraction of entries where all expected outputs matched
- **Accuracy (Finished):** Same, but only counting entries that terminated normally

## Key Files

- `run_benchforce.py` - Text-mode wrapper for egi-bench integration
- `requirements_text.txt` - Minimal dependencies (no audio/voice packages)
- `run.py` - Original benchforce entry point
- `src/environments/` - Environment definitions (hospital, hr_software)
- `src/classes/agents/impl/openai.py` - OpenAI agent with function calling
- `src/metrics/accuracy.py` - Accuracy metric implementation

## Changes from upstream

1. **Lazy audio imports** in `src/classes/provider.py` - ElevenLabs and Deepgram imports are deferred so text mode doesn't require audio packages
2. **Lazy audio imports** in `src/classes/noise.py` - pydub/scipy imports wrapped in try/except for text mode
3. **Text-only communicator** in `src/classes/communicator.py` - Added `TextOnlyCommunicator` that skips TTS/STT initialization; used when both agent and client are in text mode
4. **Default to OpenAI provider** in `src/classes/provider.py` - Unknown model names fall back to OpenAI provider (for LiteLLM-proxy compatibility — the proxy speaks the OpenAI wire format regardless of upstream)
5. **`run_benchforce.py`** - Wrapper script that generates text-mode config.yaml and runs the benchmark
6. **`requirements_text.txt`** - Stripped-down requirements without audio dependencies (deepgram-sdk, elevenlabs, librosa, pydub, scipy)
